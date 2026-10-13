"""Transfer a registered AU voice into Vocoflex's own persisted standalone state.

Storage encoding follows JUCE MemoryBlock's documented legacy encoding:
https://docs.juce.com/master/classjuce_1_1MemoryBlock.html
Only run while Vocoflex is closed, after its own settings have been saved.
"""
import json
import math
from pathlib import Path
import plistlib
import shutil
import uuid
import xml.etree.ElementTree as ET

TABLE = '.ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+'


def decode(value):
    size, payload = value.split('.', 1)
    size = int(size)
    if size < 0 or size > 16_000_000 or len(payload) != (size * 8 + 5) // 6:
        raise ValueError('Unsupported Vocoflex state encoding')
    result = bytearray(size)
    for index, char in enumerate(payload):
        bits = TABLE.index(char)
        bit = index * 6
        byte, offset = divmod(bit, 8)
        if byte < size:
            result[byte] |= (bits << offset) & 255
        if offset > 2 and byte + 1 < size:
            result[byte + 1] |= bits >> (8 - offset)
    return bytes(result)


def encode(data):
    chars = []
    for bit in range(0, len(data) * 8, 6):
        byte, offset = divmod(bit, 8)
        value = data[byte] >> offset
        if offset > 2 and byte + 1 < len(data):
            value |= data[byte + 1] << (8 - offset)
        chars.append(TABLE[value & 63])
    return f'{len(data)}.' + ''.join(chars)


def apply(command):
    settings = Path(command['settingsPath'])
    shift = float(command['shift'])
    if not math.isfinite(shift) or abs(shift) > 12:
        raise ValueError('Invalid calibrated pitch')
    tree = ET.parse(settings)
    root = tree.getroot()
    state = root.find('State')
    if state is None or not state.get('savedState'):
        raise ValueError('Vocoflex를 한 번 실행하고 종료한 뒤 다시 시도해 주세요.')
    old = json.loads(decode(state.get('savedState')))
    with open(command['statePath'], 'rb') as file:
        target = json.loads(plistlib.load(file)['jucePluginState'])
    if not target.get('voice', {}).get('sources'):
        raise ValueError('참고 음색이 등록되지 않은 프리셋입니다.')
    updated = {**old, 'voice': target['voice'], 'inputPitchShift': shift,
               'presetName': command.get('name', 'Hinana'), 'useRealtimeLatency': True}
    state.set('savedState', encode(json.dumps(updated, ensure_ascii=False).encode('utf-8')))
    if command.get('inputName') and command.get('outputName'):
        audio = root.find('Audio')
        if audio is None:
            audio = ET.SubElement(root, 'Audio')
        setup = ET.fromstring(audio.get('audioSetup', '<DEVICESETUP/>'))
        if command.get('platform') == 'win32':
            mapping = {'Windows WASAPI': 'Windows Audio', 'Windows DirectSound': 'DirectSound', 'MME': 'Windows Audio'}
            input_api, output_api = command.get('inputApi'), command.get('outputApi')
            if input_api != output_api or input_api not in mapping:
                raise ValueError('Vocoflex 자체 설정에는 같은 Windows 오디오 API의 입력과 출력을 선택해 주세요.')
            if input_api == 'MME':
                raise ValueError('장치 이름이 잘리지 않는 Windows WASAPI 입력과 출력을 선택해 주세요.')
            setup.set('deviceType', mapping[input_api])
        else:
            setup.set('deviceType', 'CoreAudio')
        setup.set('audioInputDeviceName', command['inputName'])
        setup.set('audioOutputDeviceName', command['outputName'])
        setup.set('audioDeviceRate', '48000.0')
        audio.set('audioSetup', ET.tostring(setup, encoding='unicode'))
    # Keep a restorable, complete copy of the user's standalone configuration.
    backup = settings.with_name(f'settings.before-hinana-{uuid.uuid4()}.xml')
    shutil.copy2(settings, backup)
    temporary = settings.with_name(f'settings.{uuid.uuid4()}.tmp')
    try:
        tree.write(temporary, encoding='utf-8', xml_declaration=True)
        verified = json.loads(decode(ET.parse(temporary).getroot().find('State').get('savedState')))
        if verified != updated:
            raise RuntimeError('Vocoflex 설정 검증에 실패했습니다.')
        temporary.replace(settings)
    finally:
        temporary.unlink(missing_ok=True)
    return {'backupPath': str(backup), 'shift': shift, 'name': updated['presetName'],
            'sources': len(updated['voice']['sources'])}
