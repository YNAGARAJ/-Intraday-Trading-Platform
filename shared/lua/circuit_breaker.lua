-- circuit_breaker.lua
-- Atomic Halt Flag State Transition.
-- ARGV[1] = current_pnl_pct, ARGV[2] = limit (e.g. -2.0).
-- Returns 1 if halted, 0 otherwise.
local current_pnl_pct = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
if current_pnl_pct <= limit then
    redis.call('SET', 'system:status:halted', 'true')
    redis.call('SET', 'system:status:reason', 'DAILY_LOSS_LIMIT_VIOLATION')
    return 1
end
return 0
