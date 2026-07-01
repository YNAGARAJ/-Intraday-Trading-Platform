-- signal_dedup.lua
-- Atomic signal dedup + halt check before publishing to Redis Streams.
-- KEYS[1] = dedup key (e.g. "signal:dedup:<symbol>:<direction>")
-- KEYS[2] = signal stream key (e.g. "signals:generated")
-- ARGV[1] = dedup window seconds
-- ARGV[2] = serialized SignalGenerated protobuf bytes (as Redis bulk string)
-- Returns {1, "PUBLISHED", stream_entry_id} or {0, "HALTED"} or {0, "DUPLICATE"}.
local dedup_key = KEYS[1]
local stream_key = KEYS[2]
local ttl_secs = tonumber(ARGV[1])
local payload = ARGV[2]

local halted = redis.call('GET', 'system:status:halted')
if halted == 'true' then
    return {0, 'HALTED'}
end

local existing = redis.call('EXISTS', dedup_key)
if existing == 1 then
    return {0, 'DUPLICATE'}
end

redis.call('SET', dedup_key, '1', 'EX', ttl_secs)
local entry_id = redis.call('XADD', stream_key, '*', 'data', payload)

return {1, 'PUBLISHED', entry_id}
