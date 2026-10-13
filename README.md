# LLM → VOICEPEAK → Vocoflex

한국어 키보드 입력을 `gpt-5.6-sol`에 보내 일본어 답변을 만든 뒤, VOICEPEAK로 합성한 WAV를 가상 오디오 장치에 재생하는 데스크톱 앱입니다. 일본어 응답 아래에는 같은 모델이 만든 자연스러운 한국어 번역을 작은 자막으로 병기합니다.

현재 버전은 모델 답변의 문장 수와 글자 수를 제한하지 않습니다. 긴 답변은 일본어 문장부호를 기준으로 VOICEPEAK의 140자 제한보다 여유 있는 120자 이하로 자동 분할하여 순서대로 합성·재생합니다.
모델에는 일본어 구두점 `、`와 `。`를 사용하도록 지시하며, 누락된 줄 끝과 강제 분할 지점에도 음성용 구두점을 자동으로 보완합니다.

## Electron 멀티 OS 앱

### 목표 WAV 바로 등록 (0.12.2)

**Vocoflex 자동 설정 → 목표 WAV 등록…**에서 `hinana_2min.wav` 같은 목표 파일을 선택하세요.
파일 자체의 음높이를 분석한 뒤 Vocoflex Import로 같은 파일을 가져오고 **등록 저장**을 누르면,
파일 이름으로 목표 목소리를 저장하고 자동 선택합니다. 이어서 입력·출력 장치를 고르고 8초 분석을 시작하세요.
이 자동 보정용 목표 등록에는 API 키나 VOICEPEAK 합성·미리 듣기가 필요하지 않습니다.
대화용 음성 프리셋은 기존 비교·미리 듣기 흐름으로 별도로 만듭니다.

### Windows 음성 프리셋·자동 보정 (0.12.0)

Windows에서도 음성 프리셋 등록, 미리 듣기, 대화 음성 변환, 앱 내부 실시간 변환,
Vocoflex 자체 자동 보정을 사용할 수 있습니다. 설치·활성화된 **Vocoflex VST3**가 필요합니다.
기본 플러그인 경로는 `C:\Program Files\Common Files\VST3\Vocoflex.vst3`입니다.
Windows 변환 호스트는 앱에 포함되어 Python을 따로 설치할 필요가 없습니다.

**음성 프리셋 → 참고 음성 선택 → 음색 등록**에서 Vocoflex Import로 참고 WAV를 가져온 뒤,
별도 안내 창의 **등록 저장**을 누르세요. 분석·미리 듣기 후 프리셋을 저장하면 대화에 적용할 수 있습니다.

**Vocoflex 자동 설정**에서 저장한 프리셋과 마이크·헤드폰을 선택해 8초 분석을 시작하세요.
Windows 자체 설정 모드에서는 WASAPI 장치만 표시합니다. 설정 적용 시 Vocoflex를 정상 종료하고
전체 설정 파일을 백업한 다음 새 보정값으로 다시 실행합니다. 종료가 거부되면 열려 있는 대화상자를 닫고 재시도하세요.
앱 내부 실시간 변환 모드는 앱이 열려 있는 동안 동작하며 중지 시 변환 프로세스도 함께 정리합니다.
Windows 메시지 루프에서 음색 복원을 검증하고, 입력 녹음에 기존 마이크 증폭값이 중복 적용되지 않도록 처리합니다.

Windows 호스트는 [Pedalboard VST3 API](https://spotify.github.io/pedalboard/reference/pedalboard.html)를 사용합니다.
macOS는 기존 AU 호스트를 사용합니다. 참고 음색은 로컬 프리셋으로 저장되며 배포 파일에 포함되지 않습니다.

### Vocoflex 자체 자동 설정 (macOS 0.11.0)

상단 **Vocoflex 자동 설정**에서 사용 방식을 **Vocoflex 자체에 자동 설정**으로 두고 히나나 프리셋, 평소 사용하는 입력 마이크, 출력 헤드폰을 선택하세요. **8초 분석 후 Vocoflex에 적용**을 누르고 평소처럼 말하면 입력을 분석하고 시험 변환한 보정값을 Vocoflex 본체에 저장합니다. Vocoflex는 설정을 정상 저장하며 종료한 뒤 새 설정으로 다시 실행됩니다.

적용 후에는 Hinana Voice를 닫아도 Vocoflex 자체가 선택한 입력을 변환합니다. 마이크로 직접 말하려면 입력에 실제 마이크를 선택하고, 다른 앱의 소리를 변환하려면 가상 케이블을 선택하세요. 입력 화자나 마이크가 달라지면 다시 분석합니다. 설정 파일 전체는 Vocoflex 설정 폴더의 `settings.before-hinana-*.xml`에 백업됩니다.

Vocoflex 1.0.3의 저장 형식을 실제 앱에서 재실행·확인했습니다. [JUCE MemoryBlock 저장 인코딩](https://docs.juce.com/master/classjuce_1_1MemoryBlock.html)을 사용하며 라이선스 파일에는 접근하지 않습니다. 이 기능은 음색과 고정 피치를 맞추고 말투·억양은 원래 발성을 따릅니다.

### 실시간 자동 맞춤 (macOS 0.10.0)

상단 **실시간 자동 맞춤**에서 **히나나** 프리셋, 입력 마이크 또는 가상 케이블, 듣는 헤드폰을 선택하고 **자동 맞춤 시작**을 누르세요. 첫 8초 동안 평소 목소리로 말하거나 케이블로 입력 음성을 재생하면 참고 음높이를 기준으로 보정값을 계산하고 시험 변환 후 실시간 변환을 시작합니다. API 키와 VOICEPEAK 합성은 필요하지 않습니다.

Vocoflex AU를 앱 내부에서 계속 실행하며, 등록된 참고 음색과 입력별 피치 보정을 적용합니다. 따로 실행한 Vocoflex 앱의 설정을 변경하는 기능은 아닙니다. 최초 실행에는 macOS 마이크 권한이 필요합니다. 가상 케이블 입력은 원본 앱의 출력을 그 케이블로 지정하세요. 마이크 입력은 헤드폰을 사용하면 스피커 소리의 재입력을 피할 수 있습니다.

입력 레벨, 보정값, 장치·플러그인 지연과 버퍼 상태가 표시됩니다. 입력 화자가 달라지면 중지하고 다시 시작하세요. 창을 닫거나 앱을 종료하면 입력도 중지되며, 분석 녹음은 임시 파일로 처리 후 삭제합니다. 현재 음높이 보정 범위는 ±12반음이고 말투·억양은 입력 음성을 따릅니다. Bluetooth 장치에는 장치 자체 지연이 추가될 수 있습니다.

### 참고 음색 프리셋 (macOS 0.9.0)

상단 **음성 프리셋**에서 참고 WAV를 선택하고 **음색 등록**을 누르세요. 열린 Vocoflex 창의 Import로 같은 파일을 가져온 뒤 **등록 저장**을 누릅니다. 이후 **음높이 분석 → 미리 듣기 → 프리셋 저장 → 대화에 적용** 순서로 진행합니다. 자동 보정값은 반음 단위로 직접 조절할 수 있고, 일본어 테스트 문장도 바꿀 수 있습니다.

적용된 프리셋은 VOICEPEAK 합성 결과를 앱 내부의 Vocoflex AU로 변환합니다. 오디오 출력은 실제 헤드폰이나 스피커를 선택하세요. 프리셋 없이 기존 가상 케이블 경로도 사용할 수 있습니다. 프리셋에 맞춘 화자·속도·VOICEPEAK 음높이가 함께 적용되며, 이 설정을 변경하면 프리셋 적용이 해제됩니다.

0.9.1부터 프리셋 적용 시 기존 실제 출력 선택을 유지하고, 가상 출력이었다면 시스템 기본 헤드폰·스피커로 자동 전환합니다. 프리셋 사용 중에는 설정에서 실제 출력만 표시합니다. 이전 버전의 가상 출력 설정이 남아 있어도 대화 재생 시 실제 출력으로 전환합니다.

참고 음성과 프리셋은 이 Mac에서 처리·저장합니다. 설치·활성화된 Vocoflex가 필요하며, 음색 등록은 최초 한 번 Vocoflex 창에서 진행합니다. 자동 보정은 발성 음높이의 중앙값을 맞추므로 억양·말투나 목소리의 동일성을 보장하지 않습니다. 문장마다 변환 준비 시간이 추가됩니다.

### Vocoflex 자동 실행 (0.8.0)

설정의 **Vocoflex 연결 → Hinana Voice를 켤 때 Vocoflex도 자동 실행**을 켜고 저장하세요.
Windows/macOS에서 실행 중인지 먼저 확인하고, 꺼져 있을 때만 실행합니다.
기본 설치 경로를 자동 탐색하며 다른 위치에 설치했다면 실행 파일 선택 버튼을 사용하세요.
자동 실행은 기본적으로 꺼져 있습니다. 상단 Vocoflex 버튼으로 수동 실행하거나 상태를 확인할 수 있습니다.
실행 중 표시는 프로세스 상태이며, Vocoflex의 입력·출력 장치나 라이선스 준비 여부를 뜻하지 않습니다.
앱을 닫아도 Vocoflex는 계속 실행됩니다.

대화 중에도 다음 메시지를 작성할 수 있고, 한국어 조합 중 Enter가 잘못 전송되는 문제를 수정했습니다.
번역 실패는 자막 영역에 표시됩니다. 설정에는 API 키를 저장하지 않습니다.

Windows와 macOS에서 동일한 대화 UI와 음성 처리 흐름을 사용합니다.

```text
Electron → OpenAI Responses API → VOICEPEAK CLI → 임시 WAV
         → Windows: VB-CABLE / macOS: VB-Cable 또는 BlackHole
         → Vocoflex → 실제 헤드폰
```

운영체제별 처리는 자동으로 선택됩니다.

- Windows: VOICEPEAK 설치 경로와 DirectSound → MME → WASAPI 순서 감지
- macOS: VOICEPEAK 앱 번들의 CLI 자동 탐색과 Core Audio 사용
- 가상 출력: Windows `CABLE Input`, macOS `VB-Cable`, `BlackHole`, `Loopback Audio` 감지
- 장치 번호 대신 이름과 호스트 API도 저장하므로 재부팅 후 번호가 바뀌어도 다시 찾음
- 배포 앱에는 독립 Python 백엔드가 포함되므로 최종 사용자에게 Python 설치가 필요하지 않음
- 일본어 첫 문장은 준비되는 즉시 재생하며, 뒤 문장 합성과 한국어 번역을 백그라운드에서 병렬 처리

### 개발 환경 준비

```powershell
npm install
npm run setup
npm start
```

`npm run setup`은 프로젝트의 `.venv`에 Python 의존성과 PyInstaller를 설치합니다. macOS 터미널에서도 동일한 명령을 사용합니다.

### 운영체제별 패키징

```powershell
npm run dist
```

- Windows에서 실행: portable EXE 생성
- macOS에서 실행: 현재 CPU 아키텍처용 DMG 생성
- Git 태그 또는 수동 실행: `.github/workflows/build-desktop.yml`에서 Windows/macOS를 병렬 빌드

macOS 외부 배포에는 Apple Developer ID 서명과 notarization 설정이 별도로 필요합니다. 서명 없이 만든 로컬 DMG는 개발 및 직접 테스트용입니다.

### macOS 오디오 설정

1. VOICEPEAK와 Vocoflex를 설치하고 활성화합니다.
2. VB-CABLE for Mac 또는 BlackHole을 설치합니다.
3. 앱의 설정에서 감지된 가상 출력 장치를 선택합니다.
4. Vocoflex 입력에서도 같은 가상 장치를 선택합니다.
5. Vocoflex 출력은 실제 헤드폰으로 설정합니다.

VOICEPEAK CLI 경로나 장치 이름이 자동 감지되지 않으면 톱니바퀴 설정에서 직접 선택할 수 있습니다.

## GUI 프로그램

Python으로 바로 실행하려면:

```powershell
cd D:\LLMtoHinana
python .\hinana_app.py
```

독립 실행 파일을 만들려면:

```powershell
cd D:\LLMtoHinana
.\build.ps1
```

빌드가 끝나면 `dist\HinanaVoice.exe`를 더블클릭해서 실행합니다. 프로그램 화면에서 OpenAI API 키를 입력하면 되며, API 키는 설정 파일에 저장하지 않습니다.

## 현재 PC에 맞춘 기본값

- VOICEPEAK: `C:\Program Files\VOICEPEAK\voicepeak.exe`
- 화자: `Koharu Rikka`
- VB-CABLE 출력 장치 검색어: `CABLE Input`
- OpenAI 모델: `gpt-5.6-sol`

## 설치 및 실행

PowerShell에서 다음을 실행합니다.

```powershell
python -m pip install -r requirements.txt
$env:OPENAI_API_KEY = "여기에_API_키"
python .\hinana_voice.py --check
python .\hinana_voice.py
```

API 키를 다음 PowerShell에서도 사용하려면 사용자 환경변수로 저장한 뒤 새 PowerShell을 여세요.

```powershell
setx OPENAI_API_KEY "여기에_API_키"
```

Vocoflex에서는 입력을 `CABLE Output (VB-Audio Virtual Cable)`로, 출력을 실제 이어폰이나 헤드폰으로 설정합니다.

## 확인 및 설정 변경

```powershell
# 설치된 VOICEPEAK 화자
python .\hinana_voice.py --list-narrators

# 사용 가능한 오디오 출력 장치
python .\hinana_voice.py --list-devices

# 다른 화자 또는 명시적인 오디오 장치 번호 사용
python .\hinana_voice.py --narrator "Koharu Rikka" --device 12
```

경로나 기본값은 실행 옵션 외에 `VOICEPEAK_PATH`, `VOICEPEAK_NARRATOR`, `VB_CABLE_NAME`, `OPENAI_MODEL` 환경변수로도 바꿀 수 있습니다.

## 문제 해결

- `--check`에서 API 키만 실패하는 것은 키를 아직 넣지 않았다는 뜻입니다.
- `CABLE Input`을 못 찾으면 VB-CABLE 설치 여부를 확인한 뒤 `--list-devices` 결과의 장치 번호를 `--device`에 지정하세요.
- 원음은 Python이 `CABLE Input`으로만 보냅니다. Windows 기본 출력을 CABLE로 바꿀 필요는 없습니다.
