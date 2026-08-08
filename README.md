# LLM → VOICEPEAK → Vocoflex

한국어 키보드 입력을 `gpt-5.6-sol`에 보내 일본어 답변을 만든 뒤, VOICEPEAK로 합성한 WAV를 가상 오디오 장치에 재생하는 데스크톱 앱입니다. 일본어 응답 아래에는 같은 모델이 만든 자연스러운 한국어 번역을 작은 자막으로 병기합니다.

현재 버전은 모델 답변의 문장 수와 글자 수를 제한하지 않습니다. 긴 답변은 일본어 문장부호를 기준으로 VOICEPEAK의 140자 제한보다 여유 있는 120자 이하로 자동 분할하여 순서대로 합성·재생합니다.
모델에는 일본어 구두점 `、`와 `。`를 사용하도록 지시하며, 누락된 줄 끝과 강제 분할 지점에도 음성용 구두점을 자동으로 보완합니다.

## Electron 멀티 OS 앱

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
