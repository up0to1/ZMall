package com.hmall.user.service.impl;

import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.hmall.api.dto.CreditsBalanceDTO;
import com.hmall.api.dto.CreditsResultDTO;
import com.hmall.common.config.RedisConstants;
import com.hmall.common.exception.BadRequestException;
import com.hmall.common.exception.BizIllegalException;
import com.hmall.user.domain.po.AiCreditsAccount;
import com.hmall.user.domain.po.AiCreditsRecharge;
import com.hmall.user.enums.QuotaType;
import com.hmall.user.mapper.AiCreditsAccountMapper;
import com.hmall.user.mapper.AiCreditsRechargeMapper;
import com.hmall.user.service.ICreditsService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * AI Credits 积分制配额服务实现（v3）
 *
 * <p>Redis Key 设计（{@code RedisConstants.AI_CREDITS_*}）：
 * <pre>
 * ai:credits:free:{userId}       → Hash, field=过期时间戳(秒), value=该批次剩余数量
 * ai:credits:paid:{userId}       → String, 充值 credits 总余额（永久）
 * ai:credits:frozen:{userId}:{taskId} → String(JSON), 扣减明细 {free:[{ts,count},...], paid:int, total:int}
 * ai:credits:award:limit:{userId}:{awardType}:{date} → String, 每日奖励计数
 * </pre>
 *
 * <p>核心 Lua 脚本：
 * <ul>
 *   <li>{@link #DEDUCT_LUA}：FIFO 扣减（先扣 free Hash 按到期升序，再扣 paid String）+ 写冻结明细</li>
 *   <li>{@link #ROLLBACK_LUA}：读冻结明细，按原路返还（free 返还到原 expireTs 批次，paid 累加）</li>
 * </ul>
 *
 * <p>v3.1 失败规则：
 * <ul>
 *   <li>阶段一失败：全额 rollback</li>
 *   <li>阶段二 VTON 全部失败：全额 rollback</li>
 *   <li>阶段二 VTON 部分失败：调用 confirm（部分失败不退还 credits）</li>
 *   <li>VTON API 故障：全额 rollback</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class CreditsServiceImpl implements ICreditsService {

    private final StringRedisTemplate stringRedisTemplate;
    private final AiCreditsAccountMapper accountMapper;
    private final AiCreditsRechargeMapper rechargeMapper;
    private final com.hmall.user.mapper.UserMapper userMapper;  // 扣减 user.balance（钱包余额）

    /** 每日奖励计数 Key 前缀：ai:credits:award:limit:{userId}:{awardType}:{date} */
    private static final String AWARD_DAILY_LIMIT_PREFIX = "ai:credits:award:limit:";

    /**
     * P1-9 修复：奖励每日上限校验 Lua 脚本（原子化 check + increment + expire）
     * KEYS[1]=limitKey
     * ARGV[1]=dailyLimit  ARGV[2]=ttlSeconds
     * 返回: 1=允许发放（计数已+1），0=已达上限
     */
    private static final String AWARD_LIMIT_LUA =
            "local cur = tonumber(redis.call('GET', KEYS[1]) or '0')\n" +
            "if cur >= tonumber(ARGV[1]) then return 0 end\n" +
            "redis.call('INCR', KEYS[1])\n" +
            "redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))\n" +
            "return 1";

    /** 即将过期阈值：剩余 ≤3 天视为即将过期（用于前端高亮提示） */
    private static final long EXPIRING_SOON_THRESHOLD_SECONDS = 3 * 24 * 3600L;

    /**
     * 预扣 Lua 脚本
     * KEYS[1]=freeHashKey  KEYS[2]=paidKey  KEYS[3]=frozenKey
     * ARGV[1]=creditsNeeded  ARGV[2]=frozenTtl  ARGV[3]=currentTime(秒)
     * 返回:
     *   "ok:{freeUsed}:{paidUsed}:{balanceAfter}" 成功
     *   "refused" 余额不足
     *
     * 步骤：
     *   1. 扫描 free Hash，清理过期项（field < currentTime）
     *   2. 计算 totalFree + paid，与 needed 比较
     *   3. FIFO 扣减：按 field（过期时间）升序扣 free，不足扣 paid
     *   4. 扣减明细写入 frozenKey（JSON）
     *   5. 返回 "ok:{freeUsed}:{paidUsed}:{balanceAfter}"
     */
    private static final String DEDUCT_LUA =
            "local freeHash = redis.call('HGETALL', KEYS[1])\n" +
            "local currentTime = tonumber(ARGV[3])\n" +
            "local needed = tonumber(ARGV[1])\n" +
            "local totalFree = 0\n" +
            "local freeEntries = {}\n" +
            "for i = 1, #freeHash, 2 do\n" +
            "    local expireTs = freeHash[i]\n" +
            "    local count = tonumber(freeHash[i+1])\n" +
            "    if tonumber(expireTs) < currentTime then\n" +
            "        redis.call('HDEL', KEYS[1], expireTs)\n" +
            "    else\n" +
            "        totalFree = totalFree + count\n" +
            "        table.insert(freeEntries, {tonumber(expireTs), count, expireTs})\n" +
            "    end\n" +
            "end\n" +
            "local paid = tonumber(redis.call('GET', KEYS[2]) or '0')\n" +
            "local total = totalFree + paid\n" +
            "if total < needed then\n" +
            "    return 'refused'\n" +
            "end\n" +
            "table.sort(freeEntries, function(a, b) return a[1] < b[1] end)\n" +
            "local freeUsed = 0\n" +
            "local paidUsed = 0\n" +
            "local freeDetail = {}\n" +
            "for _, entry in ipairs(freeEntries) do\n" +
            "    if needed <= 0 then break end\n" +
            "    local expireTsNum = entry[1]\n" +
            "    local count = entry[2]\n" +
            "    local expireTsStr = entry[3]\n" +
            "    if count <= needed then\n" +
            "        freeUsed = freeUsed + count\n" +
            "        needed = needed - count\n" +
            "        redis.call('HDEL', KEYS[1], expireTsStr)\n" +
            "        table.insert(freeDetail, {expireTsStr, count})\n" +
            "    else\n" +
            "        freeUsed = freeUsed + needed\n" +
            "        redis.call('HSET', KEYS[1], expireTsStr, count - needed)\n" +
            "        table.insert(freeDetail, {expireTsStr, needed})\n" +
            "        needed = 0\n" +
            "    end\n" +
            "end\n" +
            "if needed > 0 then\n" +
            "    paidUsed = needed\n" +
            "    redis.call('SET', KEYS[2], paid - needed)\n" +
            "    needed = 0\n" +
            "end\n" +
            "local frozenValue = cjson.encode({\n" +
            "    free = freeDetail,\n" +
            "    paid = paidUsed,\n" +
            "    total = tonumber(ARGV[1]),\n" +
            "    freeUsed = freeUsed,\n" +
            "    paidUsed = paidUsed\n" +
            "})\n" +
            "redis.call('SET', KEYS[3], frozenValue, 'EX', ARGV[2])\n" +
            "local balanceAfter = (totalFree - freeUsed) + (paid - paidUsed)\n" +
            "return 'ok:' .. freeUsed .. ':' .. paidUsed .. ':' .. balanceAfter";

    /**
     * 回滚 Lua 脚本
     * KEYS[1]=frozenKey  KEYS[2]=freeHashKey  KEYS[3]=paidKey
     * 返回: "ok" / "not_found"
     *
     * 步骤：
     *   1. 读 frozenKey 明细，不存在返回 not_found
     *   2. 删除 frozenKey
     *   3. 按 free 明细返还到 freeHash（按原 expireTs 批次累加）
     *   4. 按 paid 明细返还到 paidKey（累加）
     */
    private static final String ROLLBACK_LUA =
            "local frozen = redis.call('GET', KEYS[1])\n" +
            "if not frozen then\n" +
            "    return 'not_found'\n" +
            "end\n" +
            "redis.call('DEL', KEYS[1])\n" +
            "local detail = cjson.decode(frozen)\n" +
            "if detail.free then\n" +
            "    for _, entry in ipairs(detail.free) do\n" +
            "        local expireTs = entry[1]\n" +
            "        local count = entry[2]\n" +
            "        local cur = tonumber(redis.call('HGET', KEYS[2], expireTs) or '0')\n" +
            "        redis.call('HSET', KEYS[2], expireTs, cur + count)\n" +
            "    end\n" +
            "end\n" +
            "if detail.paid and detail.paid > 0 then\n" +
            "    local cur = tonumber(redis.call('GET', KEYS[3]) or '0')\n" +
            "    redis.call('SET', KEYS[3], cur + detail.paid)\n" +
            "end\n" +
            "return 'ok'";

    private final DefaultRedisScript<String> deductScript = new DefaultRedisScript<>(DEDUCT_LUA, String.class);
    private final DefaultRedisScript<String> rollbackScript = new DefaultRedisScript<>(ROLLBACK_LUA, String.class);
    // P1-9 修复：奖励每日上限校验脚本（返回 Long：1=允许，0=已达上限）
    private final DefaultRedisScript<Long> awardLimitScript = new DefaultRedisScript<>(AWARD_LIMIT_LUA, Long.class);

    @Override
    public CreditsResultDTO deduct(QuotaType type, Long userId, String taskId, int credits) {
        if (!type.isCreditsMode()) {
            throw new BadRequestException("非 credits 模式的配额类型不能调用 credits 接口: " + type);
        }
        validate(userId, taskId);
        if (credits <= 0) {
            throw new BadRequestException("credits 数必须大于 0");
        }

        // 首次使用自动赠送 50 credits（幂等：仅在 free Hash 为空且账户未标记 firstGiftReceived 时触发）
        ensureFirstGift(userId);

        String freeHashKey = RedisConstants.AI_CREDITS_FREE_KEY + userId;
        String paidKey = RedisConstants.AI_CREDITS_PAID_KEY + userId;
        String frozenKey = RedisConstants.AI_CREDITS_FROZEN_KEY + userId + ":" + taskId;

        long currentTime = LocalDateTime.now().toEpochSecond(ZoneOffset.UTC);
        String result = stringRedisTemplate.execute(
                deductScript,
                List.of(freeHashKey, paidKey, frozenKey),
                String.valueOf(credits),
                String.valueOf(RedisConstants.AI_CREDITS_FROZEN_TTL),
                String.valueOf(currentTime)
        );

        if (result == null || result.startsWith("refused")) {
            log.warn("Credits 预扣被拒绝: type={}, userId={}, taskId={}, needed={}",
                    type.getValue(), userId, taskId, credits);
            return CreditsResultDTO.refused();
        }

        // 解析 "ok:{freeUsed}:{paidUsed}:{balanceAfter}"
        String[] parts = result.split(":");
        int freeUsed = Integer.parseInt(parts[1]);
        int paidUsed = Integer.parseInt(parts[2]);
        int balanceAfter = Integer.parseInt(parts[3]);

        log.info("Credits 预扣成功: type={}, userId={}, taskId={}, needed={}, freeUsed={}, paidUsed={}, balanceAfter={}",
                type.getValue(), userId, taskId, credits, freeUsed, paidUsed, balanceAfter);

        // 查询当前余额明细（含 expiringSoon 计算）
        CreditsBalanceDTO balance = queryBalanceInternal(userId);
        CreditsResultDTO dto = CreditsResultDTO.success(credits, balanceAfter,
                balance.getFreeBalance(), balance.getPaidBalance());
        dto.setExpiringSoon(balance.getExpiringSoon());
        return dto;
    }

    @Override
    public void confirm(QuotaType type, Long userId, String taskId) {
        if (!type.isCreditsMode()) {
            throw new BadRequestException("非 credits 模式的配额类型不能调用 credits 接口: " + type);
        }
        validate(userId, taskId);

        String frozenKey = RedisConstants.AI_CREDITS_FROZEN_KEY + userId + ":" + taskId;
        Boolean deleted = stringRedisTemplate.delete(frozenKey);

        if (Boolean.FALSE.equals(deleted)) {
            log.warn("Credits 确认时冻结记录不存在（可能已超时或已处理）: type={}, userId={}, taskId={}",
                    type.getValue(), userId, taskId);
            return;
        }

        // 异步更新账户表统计字段（非关键路径，失败不影响主流程）
        try {
            updateAccountStats(userId, 0, 0, 0, 0, 0, 1);
        } catch (Exception e) {
            log.warn("更新账户统计字段失败（不影响主流程）: userId={}, error={}", userId, e.getMessage());
        }

        log.info("Credits 确认成功: type={}, userId={}, taskId={}", type.getValue(), userId, taskId);
    }

    @Override
    public void rollback(QuotaType type, Long userId, String taskId) {
        if (!type.isCreditsMode()) {
            throw new BadRequestException("非 credits 模式的配额类型不能调用 credits 接口: " + type);
        }
        validate(userId, taskId);

        String frozenKey = RedisConstants.AI_CREDITS_FROZEN_KEY + userId + ":" + taskId;
        String freeHashKey = RedisConstants.AI_CREDITS_FREE_KEY + userId;
        String paidKey = RedisConstants.AI_CREDITS_PAID_KEY + userId;

        String result = stringRedisTemplate.execute(
                rollbackScript,
                List.of(frozenKey, freeHashKey, paidKey)
        );

        if ("not_found".equals(result)) {
            log.warn("Credits 回滚时冻结记录不存在（可能已超时或已处理）: type={}, userId={}, taskId={}",
                    type.getValue(), userId, taskId);
            return;
        }

        // 异步更新账户统计字段（rollback 次数累加）
        try {
            updateAccountStats(userId, 0, 0, 0, 0, 1, 0);
        } catch (Exception e) {
            log.warn("更新账户统计字段失败（不影响主流程）: userId={}, error={}", userId, e.getMessage());
        }

        log.info("Credits 回滚成功: type={}, userId={}, taskId={}", type.getValue(), userId, taskId);
    }

    @Override
    public CreditsBalanceDTO getBalance(Long userId) {
        if (userId == null || userId <= 0) {
            throw new BadRequestException("用户ID不合法");
        }
        // 首次使用自动赠送 50 credits（幂等）
        ensureFirstGift(userId);
        return queryBalanceInternal(userId);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public CreditsBalanceDTO recharge(Long userId, int amountFen, String payOrderNo, Integer packageId) {
        if (userId == null || userId <= 0) {
            throw new BadRequestException("用户ID不合法");
        }
        if (amountFen < 100) {
            throw new BadRequestException("最低充值 1 元");
        }
        if (StrUtil.isBlank(payOrderNo)) {
            throw new BadRequestException("支付订单号不能为空");
        }

        // 1. 幂等校验：payOrderNo 唯一
        Integer existCount = rechargeMapper.selectCount(new LambdaQueryWrapper<AiCreditsRecharge>()
                .eq(AiCreditsRecharge::getPayOrderNo, payOrderNo)
                .eq(AiCreditsRecharge::getStatus, 1));
        if (existCount != null && existCount > 0) {
            log.warn("充值订单已处理，跳过: userId={}, payOrderNo={}", userId, payOrderNo);
            return queryBalanceInternal(userId);
        }

        // 2. 计算充值 credits 数（1 元 = 5 credits，可按套餐加成）
        int credits = calculateRechargeCredits(amountFen, packageId);

        // 3. 扣减钱包余额（user.balance，原子 SQL：余额不足时返回 0 行受影响）
        //    商家/用户充值 credits 时从钱包扣钱，与 credits 增加在同一事务内
        int affected = userMapper.updateMoney(userId, amountFen);
        if (affected <= 0) {
            log.warn("钱包余额不足，充值失败: userId={}, amountFen={}, balance={}",
                    userId, amountFen, queryBalanceInternal(userId));
            throw new BadRequestException("钱包余额不足，请先充值钱包");
        }

        // 4. 写入充值记录表
        AiCreditsRecharge recharge = new AiCreditsRecharge()
                .setUserId(userId)
                .setAmountFen(amountFen)
                .setCredits(credits)
                .setPayOrderNo(payOrderNo)
                .setPackageId(packageId)
                .setStatus(1)
                .setCreateTime(LocalDateTime.now());
        rechargeMapper.insert(recharge);

        // 5. Redis 累加 paid credits
        String paidKey = RedisConstants.AI_CREDITS_PAID_KEY + userId;
        stringRedisTemplate.opsForValue().increment(paidKey, credits);

        // 6. 更新账户表
        ensureAccountExists(userId);
        updateAccountStats(userId, 0, 0, 0, credits, 0, 0);

        log.info("Credits 充值成功: userId={}, payOrderNo={}, amountFen={}, credits={}",
                userId, payOrderNo, amountFen, credits);

        return queryBalanceInternal(userId);
    }

    @Override
    public CreditsBalanceDTO award(Long userId, int credits, String awardType, String bizRefId) {
        if (userId == null || userId <= 0) {
            throw new BadRequestException("用户ID不合法");
        }
        if (credits <= 0) {
            throw new BadRequestException("奖励 credits 数必须大于 0");
        }
        if (StrUtil.isBlank(awardType)) {
            throw new BadRequestException("奖励类型不能为空");
        }

        // 1. 每日上限校验（P1-9 修复：Lua 脚本原子化 check + increment + expire，避免并发超发）
        int dailyLimit = getDailyLimit(awardType);
        String today = LocalDateTime.now().toLocalDate().toString();
        String limitKey = AWARD_DAILY_LIMIT_PREFIX + userId + ":" + awardType + ":" + today;
        Long allowed = stringRedisTemplate.execute(
                awardLimitScript,
                Collections.singletonList(limitKey),
                String.valueOf(dailyLimit),
                String.valueOf(2 * 24 * 3600)  // 2 天 TTL
        );
        if (allowed == null || allowed == 0L) {
            log.info("达到每日奖励上限，跳过: userId={}, awardType={}, dailyLimit={}",
                    userId, awardType, dailyLimit);
            return null;
        }

        // 2. 发放奖励（paid credits）
        String paidKey = RedisConstants.AI_CREDITS_PAID_KEY + userId;
        stringRedisTemplate.opsForValue().increment(paidKey, credits);

        // 3. 更新账户表
        updateAccountStats(userId, 0, 0, 0, 0, 0, 0);
        // 累加 totalAwarded（单独方法）
        incrementAwardedField(userId, credits);

        log.info("Credits 奖励成功: userId={}, awardType={}, credits={}, bizRefId={}",
                userId, awardType, credits, bizRefId);

        return queryBalanceInternal(userId);
    }

    // ============================================================
    // 内部辅助方法
    // ============================================================

    /**
     * 首次使用自动赠送 50 credits（US-AT-32）
     * 幂等：仅在 free Hash 为空且账户未标记 firstGiftReceived 时触发
     */
    private void ensureFirstGift(Long userId) {
        AiCreditsAccount account = ensureAccountExists(userId);
        if (Integer.valueOf(1).equals(account.getFirstGiftReceived())) {
            return;
        }

        // 加分布式锁防止并发赠送（lock:credits:gift:{userId}）
        String lockKey = "lock:credits:gift:" + userId;
        Boolean acquired = stringRedisTemplate.opsForValue()
                .setIfAbsent(lockKey, "1", Duration.ofSeconds(10));
        if (Boolean.FALSE.equals(acquired)) {
            // 并发赠送中，等待下次调用再校验
            return;
        }

        try {
            // 双重校验
            AiCreditsAccount fresh = accountMapper.selectOne(
                    new LambdaQueryWrapper<AiCreditsAccount>().eq(AiCreditsAccount::getUserId, userId));
            if (fresh != null && Integer.valueOf(1).equals(fresh.getFirstGiftReceived())) {
                return;
            }

            // 写入 Redis：30 天后过期
            String freeHashKey = RedisConstants.AI_CREDITS_FREE_KEY + userId;
            long expireTs = LocalDateTime.now().plusSeconds(RedisConstants.AI_CREDITS_FREE_TTL)
                    .toEpochSecond(ZoneOffset.UTC);
            stringRedisTemplate.opsForHash().put(freeHashKey, String.valueOf(expireTs),
                    String.valueOf(RedisConstants.AI_CREDITS_GIFT_AMOUNT));

            // 更新账户表
            AiCreditsAccount update = new AiCreditsAccount();
            update.setId(account.getId());
            update.setFirstGiftReceived(1);
            update.setFreeCredits(account.getFreeCredits() + RedisConstants.AI_CREDITS_GIFT_AMOUNT);
            update.setTotalGifted(account.getTotalGifted() + RedisConstants.AI_CREDITS_GIFT_AMOUNT);
            accountMapper.updateById(update);

            log.info("首次赠送 credits 已发放: userId={}, credits={}", userId, RedisConstants.AI_CREDITS_GIFT_AMOUNT);
        } finally {
            stringRedisTemplate.delete(lockKey);
        }
    }

    /**
     * 确保账户存在，不存在则创建（free=0, paid=0, firstGiftReceived=0）
     */
    private AiCreditsAccount ensureAccountExists(Long userId) {
        AiCreditsAccount account = accountMapper.selectOne(
                new LambdaQueryWrapper<AiCreditsAccount>().eq(AiCreditsAccount::getUserId, userId));
        if (account != null) {
            return account;
        }
        account = new AiCreditsAccount()
                .setUserId(userId)
                .setFreeCredits(0)
                .setPaidCredits(0)
                .setTotalGifted(0)
                .setTotalRecharged(0)
                .setTotalConsumed(0)
                .setTotalRolledBack(0)
                .setTotalAwarded(0)
                .setFirstGiftReceived(0)
                .setStatus(1)
                .setCreateTime(LocalDateTime.now())
                .setUpdateTime(LocalDateTime.now());
        try {
            accountMapper.insert(account);
        } catch (Exception e) {
            // 并发插入，重新查询
            account = accountMapper.selectOne(
                    new LambdaQueryWrapper<AiCreditsAccount>().eq(AiCreditsAccount::getUserId, userId));
            if (account == null) {
                throw new BizIllegalException("创建 credits 账户失败: userId=" + userId, e);
            }
        }
        return account;
    }

    /**
     * 内部查询余额（含过期清理 + 即将过期预警）
     */
    private CreditsBalanceDTO queryBalanceInternal(Long userId) {
        String freeHashKey = RedisConstants.AI_CREDITS_FREE_KEY + userId;
        String paidKey = RedisConstants.AI_CREDITS_PAID_KEY + userId;

        long currentTime = LocalDateTime.now().toEpochSecond(ZoneOffset.UTC);
        long expiringSoonThreshold = currentTime + EXPIRING_SOON_THRESHOLD_SECONDS;

        // 扫描 free Hash，清理过期项 + 求和 + 找最近过期
        var entries = stringRedisTemplate.opsForHash().entries(freeHashKey);
        int totalFree = 0;
        int expiringSoon = 0;
        long nearestExpiryTs = Long.MAX_VALUE;
        List<String> expiredFields = new ArrayList<>();

        for (var entry : entries.entrySet()) {
            String expireTsStr = (String) entry.getKey();
            int count = Integer.parseInt((String) entry.getValue());
            long expireTs = Long.parseLong(expireTsStr);
            if (expireTs < currentTime) {
                expiredFields.add(expireTsStr);
            } else {
                totalFree += count;
                if (expireTs < expiringSoonThreshold) {
                    expiringSoon += count;
                }
                if (expireTs < nearestExpiryTs) {
                    nearestExpiryTs = expireTs;
                }
            }
        }

        // 清理过期项
        if (!expiredFields.isEmpty()) {
            stringRedisTemplate.opsForHash().delete(freeHashKey, expiredFields.toArray());
        }

        // paid 余额
        String paidStr = stringRedisTemplate.opsForValue().get(paidKey);
        int paid = paidStr == null ? 0 : Integer.parseInt(paidStr);

        CreditsBalanceDTO dto = new CreditsBalanceDTO();
        dto.setUserId(userId);
        dto.setBalance(totalFree + paid);
        dto.setFreeBalance(totalFree);
        dto.setPaidBalance(paid);
        dto.setExpiringSoon(expiringSoon);
        if (nearestExpiryTs != Long.MAX_VALUE) {
            dto.setNearestExpiry(LocalDateTime.ofEpochSecond(nearestExpiryTs, 0, ZoneOffset.UTC));
        }
        AiCreditsAccount account = ensureAccountExists(userId);
        dto.setFirstGiftReceived(Integer.valueOf(1).equals(account.getFirstGiftReceived()));

        // 钱包余额（user.balance，单位：分）—— 充值 credits 时从此余额扣减
        com.hmall.user.domain.po.User user = userMapper.selectById(userId);
        dto.setWalletBalance(user != null && user.getBalance() != null ? user.getBalance() : 0);
        return dto;
    }

    /**
     * 更新账户表统计字段（增量更新，避免并发覆盖）
     */
    private void updateAccountStats(Long userId, int freeDelta, int paidDelta,
                                     int giftedDelta, int rechargedDelta,
                                     int rollbackDelta, int consumeDelta) {
        AiCreditsAccount account = accountMapper.selectOne(
                new LambdaQueryWrapper<AiCreditsAccount>().eq(AiCreditsAccount::getUserId, userId));
        if (account == null) {
            return;
        }
        AiCreditsAccount update = new AiCreditsAccount();
        update.setId(account.getId());
        if (freeDelta != 0) update.setFreeCredits(account.getFreeCredits() + freeDelta);
        if (paidDelta != 0) update.setPaidCredits(account.getPaidCredits() + paidDelta);
        if (giftedDelta != 0) update.setTotalGifted(account.getTotalGifted() + giftedDelta);
        if (rechargedDelta != 0) update.setTotalRecharged(account.getTotalRecharged() + rechargedDelta);
        if (rollbackDelta != 0) update.setTotalRolledBack(account.getTotalRolledBack() + rollbackDelta);
        if (consumeDelta != 0) update.setTotalConsumed(account.getTotalConsumed() + consumeDelta);
        update.setUpdateTime(LocalDateTime.now());
        accountMapper.updateById(update);
    }

    private void incrementAwardedField(Long userId, int credits) {
        AiCreditsAccount account = accountMapper.selectOne(
                new LambdaQueryWrapper<AiCreditsAccount>().eq(AiCreditsAccount::getUserId, userId));
        if (account == null) {
            return;
        }
        AiCreditsAccount update = new AiCreditsAccount();
        update.setId(account.getId());
        update.setTotalAwarded(account.getTotalAwarded() + credits);
        update.setPaidCredits(account.getPaidCredits() + credits);
        update.setUpdateTime(LocalDateTime.now());
        accountMapper.updateById(update);
    }

    /**
     * 计算充值 credits 数（1 元 = 5 credits，套餐加成）
     */
    private int calculateRechargeCredits(int amountFen, Integer packageId) {
        int yuan = amountFen / 100;
        int baseCredits = yuan * RedisConstants.AI_CREDITS_RATE_YUAN_TO_CREDITS;
        if (packageId == null) {
            return baseCredits;
        }
        // 套餐加成：1=10元50credits / 2=20元110credits / 3=50元300credits / 4=100元650credits
        switch (packageId) {
            case 1: return 50;
            case 2: return 110;
            case 3: return 300;
            case 4: return 650;
            default: return baseCredits;
        }
    }

    private int getDailyLimit(String awardType) {
        if ("RATING_PUBLISH".equals(awardType)) {
            return RedisConstants.AI_CREDITS_AWARD_RATING_DAILY_LIMIT;
        }
        if ("REJECT_REASON".equals(awardType)) {
            return RedisConstants.AI_CREDITS_AWARD_REJECT_DAILY_LIMIT;
        }
        return 0;
    }

    private void validate(Long userId, String taskId) {
        if (userId == null || userId <= 0) {
            throw new BadRequestException("用户ID不合法");
        }
        if (StrUtil.isBlank(taskId)) {
            throw new BadRequestException("任务ID不能为空");
        }
    }
}
