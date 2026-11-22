# STEP 07 제출용 증빙

실제 실행 로그에서 대표 결과를 선별한 JSON 사본이다. 원본 전체는 저장소 밖의 비공개 영구 보관소에 복사하고 SHA-256 목록으로 원본과 대조했다. `/tmp`에만 의존하지 않는다. 원본 kubeconfig·Terraform State/Plan·환경 입력값은 제출 대상에서 제외했다.

- [01-ci-ecr](01-ci-ecr/run.json): GitHub CI/Publish 성공 메타데이터와 [OIDC·Digest 로그 발췌](01-ci-ecr/publish-excerpt.json).
- [02-blue-green](02-blue-green/normal-blue-http.json): [정상 Green 전환](02-blue-green/normal-green-http.json), [재실험 기준선](02-blue-green/retry-green-baseline.json).
- [03-failure-rollback](03-failure-rollback/timeline.json): [첫 시도 오류](03-failure-rollback/first-attempt-error.json), [첫 시도 복구 타임라인](03-failure-rollback/first-attempt-timeline.json), [신규 Pod 관측](03-failure-rollback/fault-active-observations.json), [Pod별 장애](03-failure-rollback/fault-individual-pods.json), [외부 503](03-failure-rollback/fault-external.json), [외부 Blue 복구](03-failure-rollback/rollback-external.json).
- [04-recovery](04-recovery/final-resources-selected.json): [활성 Pod 원복](04-recovery/restored-active-observations.json), [원복 Pod HTTP](04-recovery/restored-individual-pods.json), [최종 외부 응답](04-recovery/final-http.json).

## 자료의 성격과 마스킹

`console-*-observation.json`은 AWS 관리자 콘솔에서 직접 조회한 당시 상태를 기록한 **관측 노트**다. AWS API JSON 응답이나 화면 캡처가 아니다. [장애 중 Healthy/Rule](03-failure-rollback/console-fault-observation.json), [Rollback Rule](03-failure-rollback/console-rollback-observation.json), [원복 Target Health](04-recovery/console-restored-health-observation.json)를 HTTP·Pod 관측과 함께 읽는다. Rule/Target 목록은 필요한 시점에 콘솔 새로 고침 후 확인했다. CLI 조회 권한을 추가하지 않았다.

AWS 계정 ID와 Assume Role 식별자는 자리표시자로 바꿨다. 내부 Pod IP는 비밀 키는 아니지만 공개에 불필요하므로 파일 전체에서 일관된 `POD_IP_n` 별칭으로 바꿔 Pod·EndpointSlice·ALB 대상 대조 의미를 유지했다. 공개 DNS·개인 공인 IP·Subnet ID·사용자 절대경로·불필요한 Kubernetes 메타데이터는 포함하지 않았다. Commit SHA, 이미지 Digest, 슬롯/버전, Pod 이름, 상태코드, 시각은 검증에 필요해 유지했다.

[SOURCES.json](SOURCES.json)은 각 제출 파일의 원본 상대경로와 원본 SHA-256을 연결한다. 제출 파일은 마스킹·필드 선별 때문에 원본과 바이트가 다르다. 원본 해시는 출처 확인용이며 제출 파일 자체의 해시는 [SHA256SUMS](SHA256SUMS)에 별도로 기록했다.

최종 리소스 JSON은 `kubectl get` 응답에서 필요한 필드만 선별했다. 콘솔 관측과 구분하며 당시 실험 종료 상태를 의미한다. 이후 유료 리소스 정리 완료를 증명하지 않는다.

7-D의 20.10초는 콘솔 확인 대기를 포함한 Patch 수락→첫 Blue 200 **관측 간격**이다. 정확한 장애 지속시간·순수 ALB 전파시간·무중단 보장으로 해석하지 않는다. 두 슬롯은 같은 이미지 Digest를 사용했다.
