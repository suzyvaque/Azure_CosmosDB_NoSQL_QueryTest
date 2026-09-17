# Azure Cosmos DB NoSQL cross-partition query test

Python `azure-cosmos` 4.16.x의 비동기 클라이언트가 Gateway 모드에서 파티션 키를
지정하지 않고 쿼리할 때 발생하는 내부 `400/1004` 쿼리 플랜 요청을 관찰하는
재현 프로젝트입니다.

## 대상 환경

- Azure Cosmos DB for NoSQL: `db-cosmos-basic-test`
- Region: 기존 계정의 Korea Central 리전 사용
- Connection mode: Gateway
- Authentication: Microsoft Entra ID (`DefaultAzureCredential`)
- Database/container: `chatbot-test` / `sessions`
- Partition key: `/session_id`
- Synthetic documents: 100
- Diagnostics: resource-specific tables in Log Analytics

> 이 저장소는 계정 키, 연결 문자열, 토큰 또는 클라이언트 암호를 사용하지 않습니다.
> `.env`에는 공개 endpoint와 리소스 이름만 기록되며 Git에서 제외됩니다.

## 사전 요구 사항

- Python 3.11 이상
- Azure CLI 로그인 및 대상 구독 선택
- Cosmos DB 계정에 리소스를 만들 수 있는 Azure RBAC 권한
- 테스트 principal에 Cosmos DB native data-plane 역할을 할당할 수 있는 권한

## 1. Azure 리소스 설정

현재 로그인한 사용자를 로컬 테스트 principal로 사용할 경우:

```powershell
az login
az account set --subscription "<subscription-name-or-id>"
.\scripts\setup-azure.ps1
```

Azure 호스팅 챗봇의 관리 ID를 사용할 경우 해당 관리 ID의 **object/principal ID**를
전달합니다. client ID나 application ID와 혼동하지 않아야 합니다.

```powershell
.\scripts\setup-azure.ps1 -PrincipalId "<managed-identity-object-id>"
```

설정 스크립트는 다음 작업을 멱등적으로 수행합니다.

1. 현재 구독에서 `db-cosmos-basic-test` 검색
2. `/session_id` 컨테이너 생성(400 RU/s)
3. principal에 `Cosmos DB Built-in Data Contributor` 할당
4. Log Analytics workspace 생성
5. Cosmos DB `allLogs`와 `AllMetrics`를 resource-specific mode로 전송
6. credential이 없는 로컬 `.env` 생성

관리 ID 인증 자체는 Azure VM, App Service, Container Apps 등 관리 ID가 연결된
Azure 호스트에서 활성화됩니다. 로컬에서는 같은 코드가 Azure CLI/개발자 자격 증명을
사용하므로 비밀정보 없이 data-plane RBAC 동작을 검증할 수 있습니다.

## Private Endpoint

현재 구성은 `vm-working-dbtest-vnet`의 `default` subnet에 Cosmos DB SQL API용
`pe-cosmos-query-test` Private Endpoint를 만듭니다. 함께 구성되는 항목은 다음과 같습니다.

- Private DNS Zone: `privatelink.documents.azure.com`
- VNet DNS link: `vm-working-dbtest-vnet-cosmos`
- Private DNS Zone Group: `cosmos-private-dns`
- Cosmos 공용 네트워크: `Disabled` 유지

```powershell
.\scripts\setup-private-endpoint.ps1
```

Private Endpoint를 사용하려면 쿼리 UI와 Python 클라이언트를 해당 VNet 내부 VM 또는 VNet에
연결된 네트워크에서 실행해야 합니다. 검증 기준은
`db-cosmos-basic-test.documents.azure.com`이 `10.1.0.5` Private IP로 해석되고 TCP 443
연결이 성공하는 것입니다. 공용 인터넷에서 실행하면 의도적으로 차단됩니다.

## 2. Python 환경과 데이터 준비

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python .\src\cosmos_query_test.py --seed --verbose
```

## Query UI

`open-query-ui` VS Code task를 실행하거나 아래 명령으로 로컬 화면을 엽니다.

```powershell
.\.venv\Scripts\streamlit.exe run .\src\app.py
```

화면에서 **PK 지정** 또는 **PK 미지정** 샘플을 고른 다음 실행합니다. PK 지정은
`/session_id = session-01`을 사용하고, PK 미지정은 cross-partition query를 사용합니다.
결과 화면은 요청별 및 합산 `Status code`, `Substatus code`, `RequestCharge`, `DurationMs`와
반환 문서 수를 보여 줍니다.

`QueryPlan 요청 수`가 1 이상이면 SDK 4.16.x가 `400/1004`
`CROSS_PARTITION_QUERY_NOT_SERVABLE` 응답을 처리하고 Gateway QueryPlan fallback을 호출한
것입니다. 이 카운터는 SDK 4.16.x의 fallback 메서드를 계측하므로, SDK 버전을 변경하면
계측 호환성을 다시 검증해야 합니다. UI는 인증 정보와 요청 authorization header를 표시하거나
저장하지 않습니다.

`--seed`는 10개의 논리 파티션에 총 100건을 upsert한 뒤 **파티션 키 없이**
cross-partition query를 실행합니다. SDK 진단 로그에는 HTTP 요청 정보가 출력될 수
있으므로 공개 이슈나 저장소에 원본 로그를 올리기 전에 헤더와 식별자를 검토하십시오.

단일 파티션 control query:

```powershell
python .\src\cosmos_query_test.py --session-id session-01 --verbose
```

## 3. `400/1004`와 ServiceAvailability 비교

1. cross-partition query를 여러 번 실행하고 UTC 실행 시각을 기록합니다.
2. 진단 로그 수집에 몇 분이 걸릴 수 있으므로 기다립니다.
3. Log Analytics에서 [KQL 분석 파일](kql/cosmos-400-1004-analysis.kql)의 쿼리를
   각각 실행합니다.
4. 같은 시간대의 Azure Monitor `ServiceAvailability`를 조회합니다.

```powershell
.\scripts\show-service-availability.ps1 -Minutes 30
```

이 계정의 `ServiceAvailability`는 1시간, 6시간, 12시간 또는 1일 단위만 지원합니다.
또한 resource-specific `CDBDataPlaneRequests` 스키마에는 `SubStatusCode` 열이 없습니다.
따라서 native Cosmos 진단 로그만으로 `400/1004`만 다른 400에서 정확히 분리할 수는
없습니다. 이 프로젝트는 SDK의 QueryPlan fallback을 `AppEvents` custom telemetry로
기록하여 해당 substatus를 보존합니다. 실측 결과는
[docs/test-results-2026-09-17.md](docs/test-results-2026-09-17.md)를 참고하십시오.

## 4. 오류 집계와 Alert

예상된 쿼리 플랜 협상 응답을 제외하는 핵심 조건은 `AppEvents` custom telemetry에서
다음과 같습니다.

```kusto
| where StatusCode >= 400
| where not(StatusCode == 400 and SubstatusCode == 1004)
```

[KQL 분석 파일](kql/cosmos-400-1004-analysis.kql)의 마지막 쿼리는 최근 5분의
`AggregatedValue`를 반환합니다. 이 프로젝트는 `400/1004`를 제외한 오류가 0보다 클
때만 경보를 발생시키는 scheduled query rule도 배포합니다.

```powershell
.\scripts\deploy-actionable-error-alert.ps1
```

이 방식은 원본 플랫폼 metric을 변경하지 않고, `400/1004`가 제외된 별도의 오류 신호를
만듭니다. KQL 결과는 Log Analytics에서 Workbook 또는 Azure Dashboard에 pin할 수 있습니다.

Metric alert는 `SubStatusCode` 차원을 제공하지 않으므로 이 필터에는 scheduled query
rule이 적합합니다. 실제 챗봇도 Cosmos 호출을 감싸 `statusCode`, `substatusCode`를 포함한
custom telemetry를 전송해야 정확한 제외 집계가 가능합니다.

## 정리

테스트가 끝난 뒤 생성한 database/container, diagnostic setting, workspace 및 RBAC
assignment가 더 이상 필요하지 않으면 Azure Portal 또는 CLI에서 제거하십시오. 기존
Cosmos DB 계정 자체는 이 프로젝트가 삭제하지 않습니다.
