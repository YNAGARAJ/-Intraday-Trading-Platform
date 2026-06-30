-- margin_guard.lua
-- Pre-Trade Margin Reservation System.
-- ARGV[1] = required margin.
-- Returns 1 (reserved) or 0 (insufficient).
local required = tonumber(ARGV[1])
local current = tonumber(redis.call('GET', 'portfolio:margin:available') or "0")
if current >= required then
    redis.call('DECRBY', 'portfolio:margin:available', required)
    return 1
end
return 0
