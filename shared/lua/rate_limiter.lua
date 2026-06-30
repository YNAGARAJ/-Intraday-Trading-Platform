-- rate_limiter.lua
-- Priority-Aware Token Bucket Rate Limiter.
-- KEYS[1] = client_id
-- ARGV[1] = tokens_per_request, ARGV[2] = bucket_capacity, ARGV[3] = fill_rate_per_ms,
-- ARGV[4] = current_time_ms, ARGV[5] = is_priority
-- Returns 1 (allowed) or 0 (rejected).
local client_id = KEYS[1]
local tokens_per_request = tonumber(ARGV[1])
local bucket_capacity = tonumber(ARGV[2])
local fill_rate_per_ms = tonumber(ARGV[3])
local current_time_ms = tonumber(ARGV[4])
local is_priority = tonumber(ARGV[5])

-- Emergency and priority lane bypasses rate checks completely (Kill Switch, SL Exits).
-- is_priority must only ever be set to 1 by kill-switch / SL-exit code paths -- enforced
-- at the application layer, not in this script, so review callers carefully (RULE 8 / change-log
-- item 8: never expose is_priority as a parameter to signal/entry code or the API layer).
if is_priority == 1 then
    return 1
end

local bucket = redis.call('HMGET', 'ratelimit:' .. client_id, 'tokens', 'last_updated')
local tokens = tonumber(bucket[1] or bucket_capacity)
local last_updated = tonumber(bucket[2] or current_time_ms)

local elapsed = current_time_ms - last_updated
tokens = math.min(bucket_capacity, tokens + (elapsed * fill_rate_per_ms))

if tokens >= tokens_per_request then
    tokens = tokens - tokens_per_request
    redis.call('HMSET', 'ratelimit:' .. client_id, 'tokens', tokens, 'last_updated', current_time_ms)
    return 1
else
    return 0
end
