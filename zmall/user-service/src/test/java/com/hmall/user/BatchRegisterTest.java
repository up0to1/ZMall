package com.hmall.user;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.hmall.common.config.JwtProperties;
import com.hmall.common.config.JwtTool;
import com.hmall.user.domain.po.User;
import com.hmall.user.mapper.UserMapper;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.context.ActiveProfiles;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * ZMall 批量注册测试用户（Spring Boot Test 版本）
 *
 * <p>运行方式：在 IDE 中右键 Run 整个类或单个测试方法
 *
 * <p>测试方法说明：
 * <ul>
 *   <li><b>batchRegisterUsers</b>：通过 MyBatis-Plus 批量插入用户到数据库，
 *       然后用 JwtTool 签发 Token，输出到 CSV 文件</li>
 *   <li><b>refreshTokens</b>：读取 CSV 中的用户信息，查询数据库验证密码，
 *       重新签发 Token，覆盖写回 CSV 文件</li>
 * </ul>
 *
 * @author ZMall
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE)
@ActiveProfiles("test")
@TestMethodOrder(MethodOrderer.MethodName.class)
class BatchRegisterTest {

    @Autowired
    private UserMapper userMapper;

    @Autowired
    private PasswordEncoder passwordEncoder;

    @Autowired
    private JwtTool jwtTool;

    @Autowired
    private JwtProperties jwtProperties;

    /** 生成用户数 */
    private static final int USER_COUNT = 1000;
    /** 统一密码 */
    private static final String PASSWORD = "123";
    /** 角色：1-普通用户 */
    private static final int ROLE = 1;

    /**
     * CSV 输出路径（相对于 ZMall 项目根目录）
     * 测试运行在 user-service 模块下，需向上两级到 ZMall 根目录
     */
    private static final Path CSV_PATH =
            Paths.get("../../users_tokens.csv").toAbsolutePath().normalize();

    /** JMeter 多轮测试分片：每片 40 个用户，共 3 片（r1/r2/r3） */
    private static final int SPLIT_SIZE = 40;
    private static final int SPLIT_COUNT = 3;

    // ==================== 测试方法 ====================

    /**
     * 批量注册用户 → 签发 Token → 写入 CSV
     *
     * <p>1. 清理数据库中已存在的测试用户（用户名匹配 aaaa~aaml）
     * <p>2. 批量插入 1000 个用户（密码 BCrypt 加密）
     * <p>3. 用 JwtTool 为每个用户签发 Token
     * <p>4. 写入 CSV 文件
     */
    @Test
    @DisplayName("批量注册 1000 个测试用户并生成 Token")
    void batchRegisterUsers() throws IOException {
        System.out.println("=".repeat(60));
        System.out.println("【测试】批量注册用户");
        System.out.println("目标: " + USER_COUNT + " 个用户 | 密码: " + PASSWORD);
        System.out.println("CSV 输出: " + CSV_PATH);
        System.out.println("=".repeat(60));

        // 1. 清理旧的测试用户（用户名范围: aaaa ~ aaml）
        int deleted = cleanOldTestUsers();
        System.out.println("[OK] 已清理旧测试用户: " + deleted + " 条");

        // 2. 批量插入用户 + 生成 Token
        long start = System.currentTimeMillis();
        List<String[]> csvLines = new ArrayList<>(USER_COUNT + 1);
        csvLines.add(new String[]{"username", "password", "token"}); // 表头

        for (int i = 0; i < USER_COUNT; i++) {
            String username = generateUsername(i);

            // 2.1 构建 User 实体（密码 BCrypt 加密）
            User user = new User();
            user.setUsername(username);
            user.setPassword(passwordEncoder.encode(PASSWORD));
            user.setPhone("");
            user.setStatus(com.hmall.user.enums.UserStatus.NORMAL);
            user.setBalance(0);
            user.setRole(ROLE);
            user.setCreateTime(LocalDateTime.now());
            user.setUpdateTime(LocalDateTime.now());

            // 2.2 插入数据库
            userMapper.insert(user);

            // 2.3 签发 Token（使用自增后的 userId）
            String token = jwtTool.createToken(user.getId(), ROLE, jwtProperties.getTokenTTL());
            csvLines.add(new String[]{username, PASSWORD, token});

            if ((i + 1) % 200 == 0) {
                System.out.printf("  进度: %d/%d ( %.1f%% )\n", i + 1, USER_COUNT,
                        (i + 1) * 100.0 / USER_COUNT);
            }
        }

        // 3. 写入 CSV
        writeCsv(CSV_PATH, csvLines);

        long elapsed = System.currentTimeMillis() - start;
        System.out.println("=".repeat(60));
        System.out.printf("完成！耗时: %d ms ( %.2f 秒 )\n", elapsed, elapsed / 1000.0);
        System.out.println("用户名范围: " + generateUsername(0) + " ~ " + generateUsername(USER_COUNT - 1));
        System.out.println("CSV 文件: " + CSV_PATH);
        System.out.println("=".repeat(60));
    }

    /**
     * 读取 CSV → 模拟登录（查数据库验证密码）→ 刷新 Token → 覆盖写回 CSV
     *
     * <p>适用场景：Token 过期后刷新，无需重新注册
     */
    @Test
    @DisplayName("读取 CSV 刷新所有用户的 Token")
    void refreshTokens() throws IOException {
        System.out.println("=".repeat(60));
        System.out.println("【测试】刷新 Token");
        System.out.println("CSV 输入: " + CSV_PATH);
        System.out.println("=".repeat(60));

        if (!Files.exists(CSV_PATH)) {
            System.err.println("[ERROR] CSV 文件不存在: " + CSV_PATH);
            System.err.println("请先运行 batchRegisterUsers 测试方法");
            Assertions.fail("CSV 文件不存在，无法刷新 Token");
        }

        // 1. 读取 CSV
        List<String[]> csvLines = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(new FileInputStream(CSV_PATH.toFile()), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.trim().isEmpty()) continue;
                csvLines.add(line.split(","));
            }
        }

        System.out.println("已读取 " + (csvLines.size() - 1) + " 条用户记录");

        // 2. 逐条处理：查数据库 → 验证密码 → 签发新 Token
        int refreshed = 0;
        int failed = 0;
        long start = System.currentTimeMillis();

        for (int i = 1; i < csvLines.size(); i++) {  // 跳过表头
            String username = csvLines.get(i)[0];
            String plainPassword = csvLines.get(i)[1];

            // 2.1 模拟登录：按用户名查询数据库
            User user = userMapper.selectOne(
                    new LambdaQueryWrapper<User>().eq(User::getUsername, username));

            if (user == null) {
                System.err.printf("  [跳过] %s: 数据库中不存在\n", username);
                failed++;
                continue;
            }

            // 2.2 验证密码（模拟登录校验）
            if (!passwordEncoder.matches(plainPassword, user.getPassword())) {
                System.err.printf("  [跳过] %s: 密码不匹配\n", username);
                failed++;
                continue;
            }

            // 2.3 签发新 Token
            String newToken = jwtTool.createToken(user.getId(), user.getRole(), jwtProperties.getTokenTTL());
            csvLines.get(i)[2] = newToken;
            refreshed++;

            if (refreshed % 200 == 0) {
                System.out.printf("  进度: %d/%d ( %.1f%% )\n", refreshed,
                        csvLines.size() - 1, refreshed * 100.0 / (csvLines.size() - 1));
            }
        }

        // 3. 覆盖写回 CSV
        writeCsv(CSV_PATH, csvLines);

        long elapsed = System.currentTimeMillis() - start;
        System.out.println("=".repeat(60));
        System.out.printf("完成！耗时: %d ms ( %.2f 秒 )\n", elapsed, elapsed / 1000.0);
        System.out.println("刷新成功: " + refreshed + " | 失败: " + failed);
        System.out.println("CSV 文件: " + CSV_PATH);
        System.out.println("=".repeat(60));
    }

    // ==================== 辅助方法 ====================

    /**
     * 清理数据库中旧的测试用户（用户名范围: aaaa ~ aaml）
     * @return 删除的记录数
     */
    private int cleanOldTestUsers() {
        int deleted = 0;
        for (int i = 0; i < USER_COUNT; i++) {
            String username = generateUsername(i);
            int rows = userMapper.delete(
                    new LambdaQueryWrapper<User>().eq(User::getUsername, username));
            deleted += rows;
        }
        return deleted;
    }

    /**
     * 写入 CSV 文件，并同步生成 JMeter 多轮测试分片（r1/r2/r3）
     */
    private void writeCsv(Path csvPath, List<String[]> lines) throws IOException {
        // 确保父目录存在
        Files.createDirectories(csvPath.getParent());
        try (PrintWriter pw = new PrintWriter(
                new OutputStreamWriter(new FileOutputStream(csvPath.toFile()), StandardCharsets.UTF_8))) {
            for (String[] row : lines) {
                pw.println(String.join(",", row));
            }
        }
        System.out.println("[OK] CSV 已写入: " + csvPath);

        // 同步生成分片文件（r1/r2/r3），供 JMeter 多轮测试使用
        writeSplitCsvs(csvPath, lines);
    }

    /**
     * 从主 CSV 拆分出 r1/r2/r3 三个分片文件，每片 SPLIT_SIZE 个用户
     * <p>命名规则：users_tokens_r1.csv / users_tokens_r2.csv / users_tokens_r3.csv
     * <p>分片范围（跳过表头）：
     * <pre>
     *   r1: 第 1~40 个用户（索引 1~40）
     *   r2: 第 41~80 个用户（索引 41~80）
     *   r3: 第 81~120 个用户（索引 81~120）
     * </pre>
     */
    private void writeSplitCsvs(Path mainCsvPath, List<String[]> lines) throws IOException {
        if (lines.size() < 2) {
            System.out.println("[SKIP] 行数不足，跳过分片生成");
            return;
        }
        String[] header = lines.get(0);
        Path parent = mainCsvPath.getParent();

        for (int i = 0; i < SPLIT_COUNT; i++) {
            int from = 1 + i * SPLIT_SIZE;                       // 起始索引（含）
            int to = Math.min(1 + (i + 1) * SPLIT_SIZE, lines.size()); // 结束索引（不含）
            if (from >= lines.size()) {
                System.out.printf("[SKIP] r%d 用户数不足（仅 %d 条），跳过\n",
                        i + 1, lines.size() - 1);
                continue;
            }
            Path splitPath = parent.resolve("users_tokens_r" + (i + 1) + ".csv");
            try (PrintWriter pw = new PrintWriter(
                    new OutputStreamWriter(new FileOutputStream(splitPath.toFile()), StandardCharsets.UTF_8))) {
                pw.println(String.join(",", header));
                for (int j = from; j < to; j++) {
                    pw.println(String.join(",", lines.get(j)));
                }
            }
            System.out.printf("[OK] 分片 r%d 已写入: %s (%d 用户)\n",
                    i + 1, splitPath, to - from);
        }
    }

    /**
     * 生成四位小写英文用户名（有序、唯一）
     * <pre>
     *   0 → aaaa, 1 → aaab, ... 25 → aaaz,
     *  26 → aaba, 27 → aabb, ...
     * 999 → aaml
     * </pre>
     */
    static String generateUsername(int index) {
        char c1 = (char) ('a' + (index / (26 * 26 * 26)) % 26);
        char c2 = (char) ('a' + (index / (26 * 26)) % 26);
        char c3 = (char) ('a' + (index / 26) % 26);
        char c4 = (char) ('a' + index % 26);
        return "" + c1 + c2 + c3 + c4;
    }
}