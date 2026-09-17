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

## 2. Python 환경과 데이터 준비

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python .\src\cosmos_query_test.py --seed --verbose
```

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

`CDBDataPlaneRequests`의 `StatusCode == 400 and SubStatusCode == 1004` 요청 수와
1분 단위 `ServiceAvailability` 변화를 나란히 비교하면 내부 쿼리 플랜 요청이 서비스
가용성 계산에 반영되는지 실측할 수 있습니다. 진단 설정 이전 요청은 소급 수집되지
않습니다.

## 4. 오류 집계와 Alert

예상된 쿼리 플랜 협상 응답을 제외하는 핵심 조건은 다음과 같습니다.

```kusto
| where StatusCode >= 400
| where not(StatusCode == 400 and SubStatusCode == 1004)
```

[KQL 분석 파일](kql/cosmos-400-1004-analysis.kql)의 마지막 쿼리는 최근 5분의
`AggregatedValue`를 반환합니다. Azure Monitor **custom log search alert**에서 결과가
0보다 큰 경우를 발화 조건으로 사용하면 됩니다. 이 방식은 원본 플랫폼 메트릭을
변경하지 않고, `400/1004`가 제외된 별도의 오류 신호를 만듭니다.

Metric alert는 `SubStatusCode` 차원을 제공하지 않으므로 이 필터에는 scheduled query
rule이 적합합니다. 필요하면 같은 KQL 결과를 애플리케이션에서 Azure Monitor custom
metric으로 발행할 수 있지만, 이 테스트에는 추가 수집 코드와 비용이 없는 log alert가
더 직접적입니다.

## 정리

테스트가 끝난 뒤 생성한 database/container, diagnostic setting, workspace 및 RBAC
assignment가 더 이상 필요하지 않으면 Azure Portal 또는 CLI에서 제거하십시오. 기존
Cosmos DB 계정 자체는 이 프로젝트가 삭제하지 않습니다.
