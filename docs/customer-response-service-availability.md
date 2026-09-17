# 문의 답변 초안

## 문의

> 400이 Cosmos DB의 ServiceAvailability 지표나 SLA 산정에 포함되는지
> 
> 포함된다면 모니터링 대시보드·알람에서 구분하거나 제외하는 권장 방법이 있을지

## 답변

이번 재현 환경에서 Python `azure-cosmos` 4.16.4 async 클라이언트를 Gateway 모드로
실행하여 파티션 키 없는 cross-partition query를 20회 수행했습니다. 모든 호출에서 SDK가
`400/1004`를 수신한 뒤 QueryPlan fallback을 정확히 1회 수행했고, 쿼리는 정상 완료했습니다.
Cosmos 진단 로그에는 초기 `400` 요청이 20건 기록됐으며, 서버 처리 시간은 warm-up 이후
대부분 1ms 미만이었습니다.

동일 시간대의 Cosmos DB `ServiceAvailability`는 100.0%였습니다. 따라서 이번 실측에서는
이 예상된 Gateway QueryPlan 협상 `400/1004`가 `ServiceAvailability`를 저하시키지 않았습니다.
이는 SDK가 정상적으로 처리하는 client-side control-flow 응답이며, 서비스 장애로 해석하면
안 됩니다. 다만 공식 SLA 적용·크레딧 판단은 Azure SLA 약관과 Microsoft 지원의 최종 해석을
따라야 하므로, 이 테스트 결과만으로 계약상 SLA 산정 규칙 전체를 단정하지는 않습니다.

운영 모니터링은 플랫폼 `ServiceAvailability` alert와 애플리케이션 오류 alert를 분리하는
것을 권장합니다. `ServiceAvailability`는 플랫폼 가용성 관찰용으로 유지합니다. 반면
애플리케이션 오류는 Cosmos SDK 호출을 감싸 `statusCode`와 `substatusCode`를 Application
Insights custom telemetry에 기록하고, 다음 필터를 적용한 Log Analytics scheduled query rule로
집계·경보를 구성합니다.

```kusto
| where StatusCode >= 400
| where not(StatusCode == 400 and SubstatusCode == 1004)
```

이 방식으로 dashboard에서는 `400/1004` fallback 수와 실제 조치 대상 오류 수를 별도 타일로
표시할 수 있으며, alert는 후자만 대상으로 설정할 수 있습니다. 이번 테스트에서는 이 필터로
40개의 fallback telemetry를 제외한 결과가 0건이었고, 5분 단위 scheduled query rule
`cosmos-actionable-errors-excluding-400-1004`를 생성해 검증했습니다.

주의할 점은 Cosmos의 resource-specific 진단 테이블 `CDBDataPlaneRequests`에
`SubStatusCode` 열이 없다는 것입니다. 따라서 native diagnostic log만으로는 정확한
`400/1004` 제외가 불가능하며, 위와 같이 앱/SDK 계측으로 substatus를 보존하는 custom telemetry
방식이 필요합니다.

## 근거와 구현

- 실측 환경 및 원본 결과: [docs/test-results-2026-09-17.md](test-results-2026-09-17.md)
- Dashboard 및 alert KQL: [kql/cosmos-400-1004-analysis.kql](../kql/cosmos-400-1004-analysis.kql)
- Alert rule 배포: [scripts/deploy-actionable-error-alert.ps1](../scripts/deploy-actionable-error-alert.ps1)
