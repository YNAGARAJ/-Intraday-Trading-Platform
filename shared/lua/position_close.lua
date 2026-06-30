-- position_close.lua
-- Atomic Asset Removal & Margin Release.
-- KEYS[1] = symbol, ARGV[1] = margin_to_release.
-- Always returns 1.
local symbol = KEYS[1]
local margin_to_release = tonumber(ARGV[1])
redis.call('DEL', 'position:' .. symbol)
redis.call('SREM', 'portfolio:active_positions', symbol)
redis.call('INCRBY', 'portfolio:margin:available', margin_to_release)
return 1
