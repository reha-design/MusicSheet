# W05 전사 모델 평가 서면 설계

2026-10-05 · 기준 commit `998c0cc` · 산출물: [설계 R1](../superpowers/specs/2026-10-05-transcription-model-evaluation-design.md). 상태: **서면 설계 사용자 검토 대기**. 코드 구현·모델 비교 완료 보고서가 아니다.

## 작성한 내용

사용자가 확인한 비상업 연구·개인 개발 범위와 두 후보·MAESTRO test 12개 고정 구간 비교 방향을 서면 설계로 구체화했다. 정답을 가진 실제 음원의 동일 30초 입력·중앙 onset 구간, v2/test 대조와 SHA 기반 선정, 원본/파생 무결성 manifest, 제한된 부분 취득, MIDI tempo/건반 해제/sustain 의미를 고정했다. pitch+onset과 offset 포함 F1을 구분하고 빈 결과·실패·미측정 상태를 분리한다.

같은 호스트 CPU의 직렬·fresh process 반복 시간을 비교하고 GPU 결과는 별도 조건으로 남긴다. 정확도 차이와 불확실성·offset tradeoff·운영 적격을 사용한 선정 규칙을 예측 전에 고정했다. ByteDance benchmark 선정과 제품 연결/자동 fallback을 구분했다. root/API와 기존 Basic Pitch의 dependency/lock·제품 selector 변경은 범위에 포함하지 않았다.

새 평가 도구의 독립 환경과 기존 소유 프로세스 재사용 경계를 정의했다. ByteDance checkpoint/source 식별·호환성 probe·런타임 자동 다운로드 금지, bounded JSON/MIDI·취소/timeout·부정 입력 검증을 계획의 필수 항목으로 정했다. 아직 새로운 코드·dependency·데이터·checkpoint를 추가하지 않았다.

## 확인 근거와 자기 검토

공식 dataset·mir_eval·고정 inference/training source 및 Zenodo metadata는 [착수 조사](transcription-model-evaluation-preparation-report.md)와 설계의 직접 링크에서 참조한다. 후속 read-only 확인으로 ByteDance training TargetProcessor의 `extend_pedal=True` 기본값과 CC64 연장/재타건 처리를 확인했다. training source revision은 `1ade7dcd4348add669a67c6e6282456c8c6633bd`다. 이를 이유로 offset 정답을 key-release와 sustain으로 구분했다.

2026-10-04 공식 GCS archive에 range `0-0` header probe 결과 `206`, 전체 길이108,445,099,632 bytes, response Content-Length1을 확인했다. 응답은 header 확인 뒤 dispose했으며 전체 archive나 평가 media를 저장하지 않았다. 이 사실을 부분 취득기 구현/검증 성공으로 확대하지 않았다.

자기 검토에서 방향 승인과 서면 승인 상태, candidate dependency 경계, 실패 분모, 잘린 offset의 의미, 제품 selector와 fallback의 지원 상태를 확인했다. 서면 설계 자기 검토에는 독립 리뷰 점수를 부여하지 않는다. 실행 계획과 각 구현 단위는 AGENTS.md의 별도 독립95점 게이트를 따라야 한다.

## 검증 및 다음 단계

기존 root 회귀 **308 passed / 17 skipped / 8 deselected**(16.25s)를 확인했다. 명령은 `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest -q -p no:cacheprovider --basetemp outputs/.verification-w05/design-r1-20261005 --tb=short`다. 실제 모델 평가나 새 metric 검증의 결과가 아니며 이 문서 변경에 대한 기존 제품 회귀다. 새 행동 변경이 없어 새 테스트를 추가하지 않았다.

변경 문서 5개의 로컬 Markdown 링크 109개를 검사해 누락0을 확인했고 `git diff --check`를 통과했다. 자기 검토에서 최소 paired 표본 수8, operational recall의 분자/분모, 반복별 후보 실행 순서와 p95 계산 방식을 명확히 보완했다. 계획/구현 리뷰 점수는 아직 없다.

다음 단계는 사용자 서면 설계 검토다. 적용한 [brainstorming skill](C:/Users/user/.codex/plugins/cache/openai-curated-remote/superpowers/6.4.2/skills/brainstorming/SKILL.md)은 “written-spec approval only permits invoking writing-plans”라고 요구한다. 현재 승인된 평가 방향으로 이 설계를 완성했으며 아직 존재하지 않는 실행 계획·모델 구현의 승인으로 확장하지 않았다. 설계 검토 후 실행 계획을 작성하고 독립 평가를 받는다.
