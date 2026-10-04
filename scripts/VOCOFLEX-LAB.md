# Vocoflex Lab (macOS 실험용)

Vocoflex 1.0.3의 설치된 AU 플러그인을 사용하는 작은 호스트입니다.
참고 음색 등록, 전체 AU 상태 저장·복원, VOICEPEAK WAV 변환을 검증합니다.
자동 음색 매칭 기능은 아직 없습니다. 기존 Electron 앱에 통합하지 않았습니다.

## 빌드 및 편집 화면

```sh
node scripts/build-vocoflex-lab.js --open
```

macOS Command Line Tools와 설치·활성화된 Vocoflex AU가 필요합니다.
`artifacts/vocoflex-lab/Hinana Vocoflex Lab.app`이 생성됩니다.
일반 실행에서는 같은 폴더의 `hinana.aupreset`을 불러오고,
**Save AU State** 버튼은 `editor-session.aupreset`에 저장합니다.
참고 음성을 바꾸려면 Vocoflex의 Import 버튼을 사용하세요.
이 편집 호스트에는 실시간 마이크 입력이나 재생 기능이 없습니다.

사용자 참고 녹음은 로컬 Vocoflex에 가져왔고, 외부 분석 서비스로 전송하지 않았습니다.
원본 `/Users/hinana/Downloads/hinana_2min.wav`는 수정하지 않았습니다.
이번 실험은 70–85초의 15초 무가공 샘플을 사용했습니다.

## 별도 프로세스에서 변환

```sh
"artifacts/vocoflex-lab/Hinana Vocoflex Lab.app/Contents/MacOS/vocoflex-host" \
  --state artifacts/vocoflex-lab/hinana.aupreset \
  --input artifacts/vocoflex-lab/voicepeak-input.wav \
  --output artifacts/vocoflex-lab/my-conversion.wav \
  --fast
```

`--fast`는 AU의 공식 OfflineRender 속성을 사용합니다. 기본 모드는 오디오 길이에 맞춰 처리합니다.
출력은 48 kHz 스테레오 PCM 16-bit WAV입니다. 보고된 플러그인 지연만큼 시작을 잘라
입력과 같은 길이로 저장합니다. 목표 음색이 없는 bypass는 보고된 지연과 실제 지연이
다를 수 있으므로 원음 비교에는 `voicepeak-input.wav`를 사용하세요.

`--cursor-x`와 `--cursor-y`는 그래프 좌표(-2~2)입니다.
Vocoflex 1.0.3의 AU는 범위를 -2~2로 보고하지만 실제 accessor는 0~1 값을 사용했습니다.
호스트는 이를 변환하며 저장된 좌표로 검증했습니다. 다른 버전에서는 재검증이 필요합니다.
`--save-state PATH`를 붙이면 처리 후 상태도 저장할 수 있습니다.
실험 기준인 `hinana.aupreset`에는 덮어쓰지 마세요.

JUCE 플러그인의 상태 복원이 비동기로 이루어지므로 Cocoa 이벤트 루프를 처리한 뒤
작업을 시작합니다. 등록된 음색 자산이 복원되지 않으면 오류로 중단합니다.

## 검증과 한계

```sh
.venv/bin/python scripts/verify-vocoflex-lab.py
```

결과는 `artifacts/vocoflex-lab/validation.json`에 기록합니다.
등록 음색 자산의 복원, 커서 좌표의 저장, 출력 길이·무음·클리핑을 확인했습니다.
새로 실행한 호스트의 편집 화면에서도 참고 음색 곡선이 나타났습니다.

반복 렌더링은 같은 설정에서도 파형이 완전히 같지 않습니다. 저장·복원 과정에서
캐시된 transformation 값도 달라졌습니다. 원인은 아직 확정하지 않았습니다.
기준 상태를 고정한 반복 처리와 청취/음색 특징 비교가 필요하며, 파형 오차를
그대로 유사도 점수로 사용해서는 안 됩니다. 커서 쓰기는 검증했지만 그 음향 효과를
반복 변환의 편차와 분리해 검증하지는 못했습니다.

화자 유사도 모델과 음색 후보의 최적 탐색은 후속 단계입니다.
출력이 참고 화자와 얼마나 닮았는지는 아직 청취로 확인하지 않았습니다.

## 참고 음성에 입력 피치 맞추기

첫 샘플은 피치를 조절하지 않아 참고 녹음보다 낮았습니다. 원음과 변환본의
유성음 중앙값은 약 292 Hz, 참고 구간은 분석 설정에 따라 약 464–471 Hz였습니다.
Vocoflex의 전체 AU 상태에 있는 `inputPitchShift`를 통해 +8반음 설정을 적용했고,
변환 출력에서 약 460 Hz를 측정해 실제 반음 단위임을 확인했습니다.
자동화 파라미터 목록에는 없지만, 설치된 1.0.3의 전체 상태 저장·복원으로 제어됩니다.

```sh
.venv/bin/python -m pip install -r scripts/requirements-vocoflex-lab.txt
node scripts/build-vocoflex-lab.js
.venv/bin/python scripts/match-vocoflex-pitch.py \
  --reference artifacts/voice-reference/hinana_reference_070-085s.wav \
  --input artifacts/vocoflex-lab/voicepeak-input.wav \
  --state artifacts/vocoflex-lab/hinana.aupreset \
  --output-dir artifacts/vocoflex-lab/pitch-matched
```

Praat/Parselmouth의 자기상관 피치 추정으로 신뢰도가 높은 유성음의 중앙값을 비교해
일정한 보정량을 계산합니다. 기본적으로 보정량과 그보다 ±2반음인 후보를 생성합니다.
처리 후 출력 피치가 요청한 보정량을 따르는지도 측정합니다. 원본과 기준 프리셋은
수정하지 않습니다. 결과 파일과 측정값은 출력 폴더의 `pitch-match.json`에 기록합니다.
클리핑을 피하도록 저장 출력에 -6 dB 여유 음량을 적용합니다.

이는 **음높이 중심의 자동 보정**입니다. 말투·억양 곡선·음색 유사도까지 맞추는 기능은
아닙니다. 음색이 등록된 AU 프리셋이 먼저 필요합니다. 추정 피치에는 옥타브 오류가
있을 수 있으며, 지속적인 피치 변화가 큰 녹음은 후보를 청취해서 선택해야 합니다.

호스트 단독 사용 시 `--pitch-semitones 8`과 `--output-gain-db -6`을 지정할 수도 있습니다.
피치 보정은 -12~12반음, 출력 게인은 -60~0 dB 범위로 제한했습니다.
