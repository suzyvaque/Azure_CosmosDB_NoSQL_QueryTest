# Cosmos cross-partition query verification

## Environment

- Cosmos DB for NoSQL: `db-cosmos-basic-test`, Korea Central
- SDK: Python `azure-cosmos` 4.16.4 async
- Connection mode: Gateway
- Authentication: system-assigned managed identity on `vm-working-dbtest`
- Network: Cosmos SQL Private Endpoint via `vm-working-dbtest-vnet`

## 1. Gateway query-plan fallback

At `2026-09-17T17:24:01Z` to `17:24:02Z`, 20 partition-key-free queries were
executed from the VNet VM with `azure-cosmos` 4.16.4. Each execution recorded
`QueryPlan 요청 수 = 1` in SDK instrumentation.

Native Cosmos diagnostics from the initial equivalent test window (`17:05:57Z`)
recorded 20 `OperationName = Query`, `StatusCode = 400`, `RequestCharge = 0`
requests. The server-side `DurationMs` values ranged from `0.6246` to `60.1945`;
16 of 20 were below 1 ms. Therefore, `< 1 ms` is common after warm-up but is not
guaranteed for every request. `CDBDataPlaneRequests` does not expose a
`SubStatusCode` column; SDK fallback instrumentation identifies the `400/1004`
path because SDK 4.16.4 invokes its Gateway query-plan method only after that
specific response.

## 2. ServiceAvailability

`ServiceAvailability` for the `2026-09-17T17:00:00Z` one-hour aggregation bucket
was `100.0%`, despite 20 recorded HTTP 400 initial query requests in that hour.
The metric supports hourly (not one-minute) aggregation in this account. This
test shows that these expected Gateway query-plan `400/1004` responses did not
lower ServiceAvailability.

## 3. Excluding 400/1004 from actionable errors

The native `CDBDataPlaneRequests` table cannot implement the exact filter because
it lacks substatus. An Application Insights resource (`ai-cosmos-query-test`)
was provisioned on the same Log Analytics workspace. VM telemetry emitted 40
`CosmosQueryPlanFallback` events containing `statusCode=400` and
`substatusCode=1004` (two runs of 20).

The custom telemetry exclusion query returned:

| Fallback events | Errors after excluding 400/1004 |
| ---: | ---: |
| 40 | 0 |

Scheduled query rule `cosmos-actionable-errors-excluding-400-1004` was created.
It evaluates every five minutes and alerts only when the custom telemetry query
returns actionable errors greater than zero.
