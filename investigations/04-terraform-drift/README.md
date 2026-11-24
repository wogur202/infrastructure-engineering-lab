# Terraform 밖에서 바뀐 보안 그룹, Plan에는 어떻게 나타날까?

**Terraform · AWS Security Group · Configuration Drift**

Terraform으로 생성한 보안 그룹에 AWS 콘솔에서 직접 인바운드 규칙을 추가했다. 코드에 반영되지 않은 변경이 다음 `terraform plan`에서 어떻게 나타나는지, 그리고 실제 복구 과정에서 어느 범위까지 수정되는지 확인하기 위한 실험이다.

실험은 AWS 서울 리전(`ap-northeast-2`)에서 진행했으며, AWS CLI의 `terraform-lab` 프로필을 사용했다. 별도 VPC를 지정하지 않은 보안 그룹 구성이므로 재현하려면 해당 리전의 기본 VPC와 유효한 AWS 인증 설정이 필요하다.

## 코드에는 없지만, AWS에는 존재하는 규칙

최초 보안 그룹은 인바운드 규칙이 없는 상태로 생성했다.

```hcl
ingress = []
```

실제 리소스를 생성한 뒤 `terraform plan`을 실행했을 때는 [변경할 항목이 없었다](evidence/01-baseline/baseline-plan.txt).

```text
No changes. Your infrastructure matches the configuration.
```

이 상태를 기준으로 Terraform 코드는 수정하지 않고, AWS 콘솔에서 TCP 8080 포트를 허용하는 인바운드 규칙을 직접 추가했다. 접근 범위는 특정 IPv4 주소 하나(`/32`)로 제한했고, 규칙 설명에는 `manual-drift-test`를 남겼다.

이 시점에서 Terraform에 정의된 구성과 실제 AWS 리소스의 상태가 달라졌다.

| 구분 | 인바운드 규칙 |
|---|---|
| Terraform 코드 | 없음 |
| AWS 실제 상태 | TCP 8080 · 특정 IPv4 `/32` 허용 |

변경 전후의 보안 그룹 화면을 각각 저장했다. 이 단계에서는 Terraform이 변경을 인지했는지와 관계없이, AWS 콘솔에서 실제 설정이 달라졌다는 사실을 먼저 확인할 수 있었다.

## Terraform은 무엇을 변경하려 했나

수동 변경 이후 `terraform plan`을 실행했다.

```text
Plan: 0 to add, 1 to change, 0 to destroy.
```

Terraform은 보안 그룹을 삭제하거나 새로 생성하는 대신, 추가된 인바운드 규칙을 제거하는 [`update in-place`](evidence/02-drift/drift-plan.txt)를 제안했다.

```diff
~ ingress = [
  - {
      - description = "manual-drift-test"
      - from_port   = 8080
      - to_port     = 8080
      - protocol    = "tcp"
    }
]
```

AWS API를 통해서도 [TCP 8080 규칙이 실제로 존재한다는 사실을 확인했다](evidence/02-drift/aws-rules-after.json).

Terraform의 실행 계획과 AWS API 조회 결과가 같은 규칙을 가리키고 있었으므로, 코드 외부에서 발생한 변경을 Terraform이 감지했다는 점을 확인할 수 있었다.

다만 여기서 구분할 부분이 있다. **변경을 발견했다는 사실과 실제로 되돌렸다는 사실은 다르다.** `plan`은 어떤 작업이 필요한지 보여줄 뿐, 이 단계에서 AWS 설정을 직접 수정하지는 않는다.

## 탐지된 변경을 바로 되돌려도 될까?

이번 인바운드 규칙은 실험을 위해 직접 추가한 것이므로 원래 상태로 복구하는 것이 적절하다고 판단했다.

하지만 운영 환경에서 같은 상황이 발생한다면 변경이 이루어진 이유부터 확인해야 한다. 예를 들어 장애 대응 과정에서 임시 접근을 허용한 상태라면, Terraform의 실행 계획만 보고 즉시 제거했을 때 다른 문제가 생길 수 있다.

그렇다고 모든 수동 변경을 코드에 반영하는 것도 적절하지 않다. 변경이 필요한 이유와 적용 범위를 검토한 뒤 유지할 것인지, 원래 설정으로 되돌릴 것인지 결정해야 한다.

이번에는 유지할 이유가 없는 실험용 규칙이므로, 변경 내용을 보존한 다음 복구를 진행했다.

## 규칙을 제거한 뒤에도 차이가 남을까?

복구에 앞서 [실행 계획을 다시 생성했다](evidence/04-recovery/recovery-plan.txt). 앞서 탐지한 것과 동일하게 보안 그룹 하나를 수정하고, TCP 8080 규칙을 제거하는 내용이었다.

계획을 확인한 뒤 `terraform apply`를 실행했다.

```text
aws_security_group.drift_lab: Modifying...
aws_security_group.drift_lab: Modifications complete after 1s

Apply complete! Resources: 0 added, 1 changed, 0 destroyed.
```

수정 과정에서 보안 그룹 ID는 그대로 유지됐다. 리소스 전체를 교체하지 않고 인바운드 규칙만 변경한 것이다.

이후 AWS API에서 해당 보안 그룹의 규칙을 다시 조회했다.

```json
{
  "SecurityGroupRules": []
}
```

앞서 확인했던 [TCP 8080 규칙은 더 이상 존재하지 않았다](evidence/04-recovery/aws-rules-after-recovery.json).

마지막으로 Terraform이 실제 AWS 상태와 코드를 어떻게 판단하는지 확인하기 위해 `terraform plan`을 다시 실행했다.

```text
No changes. Your infrastructure matches the configuration.
```

[처음 정상 상태에서 확인했던 결과와 동일했다](evidence/05-validation/final-plan.txt).

이번 실험에서는 코드 외부에서 발생한 변경을 Terraform이 감지했고, 실행 계획에 따라 원래 상태로 복구할 수 있음을 확인했다. 복구 전후 모두 동일한 보안 그룹을 사용했으며, AWS API 조회 결과와 Terraform의 최종 실행 계획에서도 차이가 남지 않았다.

## 이번 실험에서 확인한 것과 남은 과제

Terraform은 코드와 실제 인프라 사이에 발생한 차이를 발견하고 이를 수정할 수 있었다. 하지만 Terraform이 변경의 의도까지 판단하는 것은 아니다.

이번에는 어떤 규칙을 누가, 왜 추가했는지 알고 있었기 때문에 복구 여부를 쉽게 결정할 수 있었다. 실제 운영 환경에서는 변경 이력이나 작업 목적을 확인하지 않은 채 자동으로 되돌리는 것이 오히려 위험할 수 있다.

따라서 개발 환경에서는 사전에 허용된 범위의 변경을 자동으로 복구하는 방식을 검토할 수 있지만, 운영 환경에서는 변경 내용을 먼저 검토하고 승인한 뒤 적용하는 방식이 더 적절할 수 있다.

이번에 검증한 범위는 수동 변경 탐지와 복구, 그리고 복구 후 상태 확인까지다. 자동 복구와 승인 절차의 실제 동작은 별도 검증이 필요하다.

---

**실험 범위와 기록**

이번 실험에서는 AWS 보안 그룹 하나에 인바운드 규칙을 추가하고 제거했다. 보안 그룹을 EC2 인스턴스에 연결하지 않았으므로 실제 서비스의 가용성이나 트래픽에 미치는 영향은 측정하지 않았다.

실험 과정에서 보존한 자료는 다음과 같다. 공개용 Terraform Plan·AWS 규칙 JSON의 계정 ID와 접속 IP는 가리거나 변수로 치환했고, 콘솔 스크린샷에도 일부 가림 처리를 했다. Drift 발생·탐지·복구를 보여 주는 규칙 변경 내용은 유지했으며, 치환값은 실제 계정이나 접속 IP를 뜻하지 않는다.

| 경로 | 기록 내용 |
|---|---|
| [`evidence/01-baseline/`](evidence/01-baseline/) | 변경 전 보안 그룹 상태와 [Terraform 실행 계획](evidence/01-baseline/baseline-plan.txt) |
| [`evidence/02-drift/`](evidence/02-drift/) | AWS 콘솔 [수동 변경](evidence/02-drift/aws-rules-after.json) 및 [Drift 탐지 결과](evidence/02-drift/drift-plan.txt) |
| [`evidence/04-recovery/`](evidence/04-recovery/) | [복구 계획](evidence/04-recovery/recovery-plan.txt), [AWS API를 통한 복구 후 상태](evidence/04-recovery/aws-rules-after-recovery.json) |
| [`evidence/05-validation/`](evidence/05-validation/) | [최종 Terraform 실행 계획](evidence/05-validation/final-plan.txt) |

실제 `terraform plan` 출력과 AWS API 조회 결과를 함께 남겨, 변경 전 상태부터 복구 후 검증까지 확인할 수 있도록 했다.