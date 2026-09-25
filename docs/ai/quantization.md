# AI Spec: Smart Quantization & Post-processing

> **Canonical Owner:** `docs/ai/quantization.md`  
> **관련 문서:** [docs/domain/score-model.md](../domain/score-model.md), [docs/ai/rhythm.md](./rhythm.md)

---

## 1. 비용 함수 기반 스마트 퀀타이즈 (Cost-based Quantization)

단순히 16분음표로 강제 스냅하면 트릴, 셋잇단음표, 루바토 표현이 깨진다. 따라서 다음 3개 비용 항의 가중합을 최소화하는 최적 음표 조합을 탐색한다.

$$\text{Cost} = w_t \cdot E_{\text{timing}} + w_c \cdot E_{\text{complexity}} + w_v \cdot E_{\text{voice}}$$

1. **$E_{\text{timing}}$ (Timing Deviation):** 원래 연주된 온셋 시간과 악보 기보 시간 사이의 오차 최소화.
2. **$E_{\text{complexity}}$ (Notation Complexity):** 불필요한 32분음표/미세 쉼표 남발 억제 및 가독성 유지.
3. **$E_{\text{voice}}$ (Voice & Staff Structure):** 왼손(Staff 2, C3 이하)과 오른손(Staff 1, C4 이상)의 자연스러운 양손 분할 및 손가락 이동성 보장.

---

## 2. 양손 분할 (Grand Staff Splitting) & music21 연동

- C3~C4 주변의 전환 영역(Split Point)을 기준으로 베이스 보표와 트레블 보표로 자동 배분한다.
- 퀀타이즈가 완료된 음표 데이터는 `music21.stream.Score` 객체로 합성된 후 표준 MusicXML로 직렬화된다.
