-- sl_linkage.lua
-- Atomic Position Entry, SL Registration & Margin Deduction.
-- KEYS[1] = symbol
-- ARGV[1] = order_id, ARGV[2] = margin_required, ARGV[3] = sl_price, ARGV[4] = strategy_id
-- Returns {1, "SUCCESS"} or {0, "INSUFFICIENT_MARGIN"}.
local symbol = KEYS[1]
local order_id = ARGV[1]
local margin_required = tonumber(ARGV[2])
local sl_price = ARGV[3]
local strategy_id = ARGV[4]

local available_margin = tonumber(redis.call('GET', 'portfolio:margin:available') or "0")
if available_margin < margin_required then
    return {0, "INSUFFICIENT_MARGIN"}
end

redis.call('DECRBY', 'portfolio:margin:available', margin_required)
redis.call('HSET', 'position:' .. symbol, 'order_id', order_id, 'sl_price', sl_price, 'strategy_id', strategy_id, 'status', 'OPEN')
redis.call('SADD', 'portfolio:active_positions', symbol)

return {1, "SUCCESS"}
