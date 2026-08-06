package com.hmall.user.service.impl;

import cn.hutool.core.util.StrUtil;
import com.hmall.api.dto.QuotaResultDTO;
import com.hmall.common.config.RedisConstants;
import com.hmall.common.exception.BadRequestException;
import com.hmall.user.enums.QuotaType;
import com.hmall.user.service.IQuotaService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.List;

/**
 * AI 配额服务实现
 *
 * Redis Key 设计：
 *   ai:quota:free:{type}:{id}:{date}     → 当日剩余免费次数（TTL 25h，覆盖跨天边界）
 *   ai:quota:paid:{type}:{id}            → 付费余额
 *   ai:quota:frozen:{type}:{id}:{taskId} → 预扣冻结记录（TTL 10min）
 *
 * 冻结记录 value 格式：
 *   "free:yyyyMMdd" → 来自免费额度，记录预扣日期，回滚时按此日期返还
 *   "paid"          → 来自付费额度，回滚时直接 INCR paidKey
 *
 * 预扣：Lua 原子操作，先免费后付费，冻结记录标记来源+日期
 * 确认：删除冻结记录（消耗已确认，不返还）
 * 回滚：读冻结记录来源+日期，删除冻结记录，对应额度 +1（跨天回滚也能返还到正确的日期 key）
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class QuotaServiceImpl implements IQuotaService {

    private final StringRedisTemplate stringRedisTemplate;

    private static final DateTimeFormatter DATE_FMT = DateTimeFormatter.ofPattern("yyyyMMdd");

    /** freeKey TTL：25 小时（86400 + 3600 秒），确保跨天边界仍有效 */
    private static final long FREE_KEY_TTL_SECONDS = 90000L;

    /**
     * 预扣 Lua 脚本
     * KEYS[1]=freeKey  KEYS[2]=paidKey  KEYS[3]=frozenKey
     * ARGV[1]=dailyFree(10)  ARGV[2]=frozenTtl(600)  ARGV[3]=freeKeyTtl(90000)  ARGV[4]=date(yyyyMMdd)
     * 返回: "free" / "paid" / "refused"
     *
     * 修复点：
     *   1. freeKey SET 时加 EX 参数（ARGV[3]），避免每日 key 永久残留
     *   2. 冻结记录 value 改为 "free:日期" 格式，回滚时按此日期返还（修复跨天回滚 bug）
     */
    private static final String DEDUCT_LUA = "local freeVal = redis.call('GET', KEYS[1])\n" +
            "if not freeVal then\n" +
            "    redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[3])\n" +
            "    freeVal = ARGV[1]\n" +
            "end\n" +
            "local free = tonumber(freeVal)\n" +
            "if free > 0 then\n" +
            "    redis.call('DECR', KEYS[1])\n" +
            "    redis.call('SET', KEYS[3], 'free:' .. ARGV[4], 'EX', ARGV[2])\n" +
            "    return 'free'\n" +
            "end\n" +
            "local paidVal = redis.call('GET', KEYS[2])\n" +
            "local paid = tonumber(paidVal) or 0\n" +
            "if paid > 0 then\n" +
            "    redis.call('DECR', KEYS[2])\n" +
            "    redis.call('SET', KEYS[3], 'paid', 'EX', ARGV[2])\n" +
            "    return 'paid'\n" +
            "end\n" +
            "return 'refused'";

    /**
     * 回滚 Lua 脚本
     * KEYS[1]=frozenKey  KEYS[2]=freeKeyPrefix  KEYS[3]=paidKey
     *   其中 freeKeyPrefix = "ai:quota:free:{type}:{id}:"（不含日期，脚本内拼接）
     * ARGV[1]=freeKeyTtl(90000)
     * 返回: "ok" / "not_found"
     *
     * 修复点：
     *   1. 从冻结记录 value 解析原始日期（"free:20260717"），拼接正确的 freeKey
     *   2. 跨天回滚时返还到预扣那天的 freeKey，而非今天的 freeKey
     *   3. 返还时如果 freeKey 已过期（不存在），重新创建并设 TTL
     */
    private static final String ROLLBACK_LUA = "local source = redis.call('GET', KEYS[1])\n" +
            "if not source then\n" +
            "    return 'not_found'\n" +
            "end\n" +
            "redis.call('DEL', KEYS[1])\n" +
            "if string.sub(source, 1, 5) == 'free:' then\n" +
            "    local date = string.sub(source, 6)\n" +
            "    local freeKey = KEYS[2] .. date\n" +
            "    local cur = redis.call('GET', freeKey)\n" +
            "    if cur then\n" +
            "        redis.call('INCR', freeKey)\n" +
            "    else\n" +
            "        -- key 已过期（跨天且超 25h），重建为 1 并设 TTL\n" +
            "        redis.call('SET', freeKey, '1', 'EX', ARGV[1])\n" +
            "    end\n" +
            "elseif source == 'paid' then\n" +
            "    redis.call('INCR', KEYS[3])\n" +
            "end\n" +
            "return 'ok'";

    private final DefaultRedisScript<String> deductScript = new DefaultRedisScript<>(DEDUCT_LUA, String.class);
    private final DefaultRedisScript<String> rollbackScript = new DefaultRedisScript<>(ROLLBACK_LUA, String.class);

    @Override
    public QuotaResultDTO deduct(String type, Long id, String taskId) {
        QuotaType quotaType = QuotaType.of(type);
        validate(id, taskId);

        String date = LocalDate.now().format(DATE_FMT);
        String freeKey = RedisConstants.AI_QUOTA_FREE_KEY + quotaType.getValue() + ":" + id + ":" + date;
        String paidKey = RedisConstants.AI_QUOTA_PAID_KEY + quotaType.getValue() + ":" + id;
        String frozenKey = RedisConstants.AI_QUOTA_FROZEN_KEY + quotaType.getValue() + ":" + id + ":" + taskId;

        String result = stringRedisTemplate.execute(
                deductScript,
                List.of(freeKey, paidKey, frozenKey),
                String.valueOf(RedisConstants.AI_QUOTA_DAILY_FREE),
                String.valueOf(RedisConstants.AI_QUOTA_FROZEN_TTL),
                String.valueOf(FREE_KEY_TTL_SECONDS),
                date
        );

        if ("refused".equals(result)) {
            log.warn("配额预扣被拒绝: type={}, id={}, taskId={}", type, id, taskId);
            return QuotaResultDTO.refused();
        }

        log.info("配额预扣成功: type={}, id={}, taskId={}, source={}, date={}", type, id, taskId, result, date);
        return QuotaResultDTO.success(result);
    }

    @Override
    public void confirm(String type, Long id, String taskId) {
        QuotaType quotaType = QuotaType.of(type);
        validate(id, taskId);

        String frozenKey = RedisConstants.AI_QUOTA_FROZEN_KEY + quotaType.getValue() + ":" + id + ":" + taskId;
        Boolean deleted = stringRedisTemplate.delete(frozenKey);

        if (Boolean.FALSE.equals(deleted)) {
            log.warn("配额确认时冻结记录不存在（可能已超时或已处理）: type={}, id={}, taskId={}", type, id, taskId);
            return;
        }

        log.info("配额确认成功: type={}, id={}, taskId={}", type, id, taskId);
    }

    @Override
    public void rollback(String type, Long id, String taskId) {
        QuotaType quotaType = QuotaType.of(type);
        validate(id, taskId);

        // freeKeyPrefix 不含日期，Lua 脚本从冻结记录解析原始日期后拼接
        String freeKeyPrefix = RedisConstants.AI_QUOTA_FREE_KEY + quotaType.getValue() + ":" + id + ":";
        String frozenKey = RedisConstants.AI_QUOTA_FROZEN_KEY + quotaType.getValue() + ":" + id + ":" + taskId;
        String paidKey = RedisConstants.AI_QUOTA_PAID_KEY + quotaType.getValue() + ":" + id;

        String result = stringRedisTemplate.execute(
                rollbackScript,
                List.of(frozenKey, freeKeyPrefix, paidKey),
                String.valueOf(FREE_KEY_TTL_SECONDS)
        );

        if ("not_found".equals(result)) {
            log.warn("配额回滚时冻结记录不存在（可能已超时或已处理）: type={}, id={}, taskId={}", type, id, taskId);
            return;
        }

        log.info("配额回滚成功: type={}, id={}, taskId={}", type, id, taskId);
    }

    private void validate(Long id, String taskId) {
        if (id == null || id <= 0) {
            throw new BadRequestException("配额主体ID不合法");
        }
        if (StrUtil.isBlank(taskId)) {
            throw new BadRequestException("任务ID不能为空");
        }
    }
}
