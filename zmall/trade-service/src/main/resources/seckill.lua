-- 通用秒杀 Lua 脚本，通过 KEYS 传入 key 前缀，复用于秒杀商品和秒杀优惠券
-- KEYS[1]: stock key 前缀
-- KEYS[2]: order set key 前缀
-- KEYS[3]: user count key 前缀
-- ARGV[1]: targetId（商品ID 或 优惠券ID）
-- ARGV[2]: userId
-- ARGV[3]: maxPerUser

local stockKeyPrefix = KEYS[1]
local orderKeyPrefix = KEYS[2]
local userCountKeyPrefix = KEYS[3]
local targetId = ARGV[1]
local userId = ARGV[2]
local maxPerUser = tonumber(ARGV[3])

local stockKey = stockKeyPrefix .. targetId
local orderKey = orderKeyPrefix .. targetId
local userCountKey = userCountKeyPrefix .. targetId .. ':' .. userId

-- 1.判断库存
local stock = redis.call('get', stockKey)
if (stock == false or tonumber(stock) <= 0) then
    return 1
end

-- 2.判断用户已购/已领数量是否超出限购/限领
local bought = tonumber(redis.call('get', userCountKey) or '0')
if (bought >= maxPerUser) then
    return 2
end

-- 3.扣库存 + 记录已购数量 + 记录订单用户
redis.call('incrby', stockKey, -1)
redis.call('incrby', userCountKey, 1)
redis.call('sadd', orderKey, userId)
return 0
