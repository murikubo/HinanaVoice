from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import sounddevice as sd
from openai import OpenAI

from hinana_voice import (
    DEFAULT_CABLE_NAME,
    DEFAULT_MODEL,
    DEFAULT_NARRATOR,
    DEFAULT_VOICEPEAK,
    ask_llm,
    list_narrators,
    make_voicepeak_wavs,
    output_devices,
    playback_candidates,
    play_to_device,
)


APP_NAME = "Hinana Voice"
SETTINGS_DIR = Path(os.getenv("APPDATA", Path.home())) / "LLMtoHinana"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"


class HinanaVoiceApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("860x680")
        self.root.minsize(720, 560)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.device_by_label: dict[str, int] = {}
        self.busy = False
        self.settings = self.load_settings()

        self.voicepeak_var = tk.StringVar(
            value=self.settings.get("voicepeak", str(DEFAULT_VOICEPEAK))
        )
        self.narrator_var = tk.StringVar(
            value=self.settings.get("narrator", DEFAULT_NARRATOR)
        )
        self.device_var = tk.StringVar()
        self.model_var = tk.StringVar(value=DEFAULT_MODEL)
        self.api_key_var = tk.StringVar(value=os.getenv("OPENAI_API_KEY", ""))
        self.speed_var = tk.IntVar(value=int(self.settings.get("speed", 95)))
        self.pitch_var = tk.IntVar(value=int(self.settings.get("pitch", 0)))
        self.status_var = tk.StringVar(value="장치를 확인하는 중입니다…")

        self.setup_style()
        self.build_ui()
        self.refresh_devices()
        self.root.after(100, self.poll_events)
        self.run_background(
            self.refresh_narrators_worker, Path(self.voicepeak_var.get().strip())
        )

    def setup_style(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Malgun Gothic", 18, "bold"))
        style.configure("Sub.TLabel", foreground="#666666")
        style.configure("Send.TButton", font=("Malgun Gothic", 11, "bold"))

    def build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Hinana Voice", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="GPT → VOICEPEAK → VB-CABLE → Vocoflex",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(0, 14))

        settings = ttk.LabelFrame(outer, text="연결 설정", padding=12)
        settings.pack(fill="x")
        settings.columnconfigure(1, weight=1)

        ttk.Label(settings, text="VOICEPEAK").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(settings, textvariable=self.voicepeak_var).grid(
            row=0, column=1, sticky="ew", pady=4
        )
        ttk.Button(settings, text="찾기", command=self.browse_voicepeak).grid(
            row=0, column=2, padx=(8, 0), pady=4
        )

        ttk.Label(settings, text="화자").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.narrator_combo = ttk.Combobox(
            settings, textvariable=self.narrator_var, state="readonly"
        )
        self.narrator_combo.grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(settings, text="새로고침", command=self.refresh_narrators).grid(
            row=1, column=2, padx=(8, 0), pady=4
        )

        ttk.Label(settings, text="VB-CABLE").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        self.device_combo = ttk.Combobox(
            settings, textvariable=self.device_var, state="readonly"
        )
        self.device_combo.grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Button(settings, text="새로고침", command=self.refresh_devices).grid(
            row=2, column=2, padx=(8, 0), pady=4
        )

        ttk.Label(settings, text="OpenAI API 키").grid(
            row=3, column=0, sticky="w", padx=(0, 8), pady=4
        )
        ttk.Entry(settings, textvariable=self.api_key_var, show="●").grid(
            row=3, column=1, sticky="ew", pady=4
        )
        ttk.Label(settings, text="저장하지 않음", style="Sub.TLabel").grid(
            row=3, column=2, padx=(8, 0), pady=4
        )

        detail = ttk.Frame(settings)
        detail.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        ttk.Label(detail, text="모델").pack(side="left")
        ttk.Entry(detail, textvariable=self.model_var, state="readonly", width=18).pack(
            side="left", padx=(6, 18)
        )
        ttk.Label(detail, text="속도").pack(side="left")
        ttk.Spinbox(detail, from_=50, to=200, textvariable=self.speed_var, width=6).pack(
            side="left", padx=(6, 18)
        )
        ttk.Label(detail, text="피치").pack(side="left")
        ttk.Spinbox(detail, from_=-300, to=300, textvariable=self.pitch_var, width=6).pack(
            side="left", padx=(6, 18)
        )
        ttk.Button(detail, text="설정 점검", command=self.check_configuration).pack(
            side="right"
        )

        conversation_frame = ttk.LabelFrame(outer, text="대화 내용 · 읽기 전용", padding=8)
        conversation_frame.pack(fill="both", expand=True, pady=(14, 10))
        self.conversation = scrolledtext.ScrolledText(
            conversation_frame,
            wrap="word",
            state="disabled",
            font=("Malgun Gothic", 11),
            padx=10,
            pady=10,
            borderwidth=0,
        )
        self.conversation.pack(fill="both", expand=True)
        self.conversation.tag_configure("user", foreground="#2457A7", spacing1=8)
        self.conversation.tag_configure("assistant", foreground="#B04474", spacing1=8)
        self.conversation.tag_configure("system", foreground="#777777", spacing1=6)

        input_frame = ttk.LabelFrame(
            outer, text="메시지 입력 · Enter로 전송 / Shift+Enter로 줄바꿈", padding=8
        )
        input_frame.pack(fill="x")
        input_frame.columnconfigure(0, weight=1)
        self.input_text = tk.Text(
            input_frame,
            height=3,
            wrap="word",
            font=("Malgun Gothic", 12),
            padx=10,
            pady=8,
            relief="solid",
            borderwidth=1,
            background="#FFFFFF",
            foreground="#111111",
            insertbackground="#111111",
        )
        self.input_text.grid(row=0, column=0, sticky="ew")
        self.input_text.bind("<Return>", self.send_from_event)
        self.input_text.bind("<Shift-Return>", self.insert_newline)
        self.send_button = ttk.Button(
            input_frame, text="말하기", style="Send.TButton", command=self.send
        )
        self.send_button.grid(row=0, column=1, padx=(10, 0), ipadx=14, ipady=5)

        ttk.Label(outer, textvariable=self.status_var, style="Sub.TLabel").pack(
            anchor="w", pady=(8, 0)
        )
        self.input_text.focus_set()

    @staticmethod
    def load_settings() -> dict[str, object]:
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}

    def save_settings(self) -> None:
        data = {
            "voicepeak": self.voicepeak_var.get().strip(),
            "narrator": self.narrator_var.get().strip(),
            "device_label": self.device_var.get(),
            "speed": self.speed_var.get(),
            "pitch": self.pitch_var.get(),
        }
        try:
            SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def browse_voicepeak(self) -> None:
        selected = filedialog.askopenfilename(
            title="voicepeak.exe 선택",
            filetypes=[("VOICEPEAK", "voicepeak.exe"), ("실행 파일", "*.exe")],
        )
        if selected:
            self.voicepeak_var.set(selected)
            self.refresh_narrators()

    def refresh_devices(self) -> None:
        previous = self.settings.get("device_label", self.device_var.get())
        host_apis = sd.query_hostapis()
        self.device_by_label.clear()
        cable_labels: list[str] = []
        other_labels: list[str] = []

        for index, device in output_devices():
            api = str(host_apis[int(device["hostapi"])]["name"])
            label = f"{index} · {device['name']} · {api}"
            self.device_by_label[label] = index
            if DEFAULT_CABLE_NAME.casefold() in str(device["name"]).casefold():
                cable_labels.append(label)
            else:
                other_labels.append(label)

        labels = cable_labels + other_labels
        self.device_combo["values"] = labels
        if previous in labels:
            self.device_var.set(str(previous))
        elif cable_labels:
            directsound = next(
                (label for label in cable_labels if "DirectSound" in label), None
            )
            self.device_var.set(directsound or cable_labels[0])
        elif labels:
            self.device_var.set(labels[0])
        self.status_var.set("오디오 장치 목록을 불러왔습니다.")

    def refresh_narrators(self) -> None:
        if self.busy:
            return
        self.status_var.set("VOICEPEAK 화자를 확인하는 중입니다…")
        self.run_background(
            self.refresh_narrators_worker, Path(self.voicepeak_var.get().strip())
        )

    def refresh_narrators_worker(self, voicepeak: Path) -> None:
        try:
            names = list_narrators(voicepeak)
            self.events.put(("narrators", names))
        except Exception as exc:
            self.events.put(("error", f"화자 조회 실패: {exc}"))

    def check_configuration(self) -> None:
        problems: list[str] = []
        voicepeak = Path(self.voicepeak_var.get().strip())
        if not voicepeak.is_file():
            problems.append("VOICEPEAK 실행 파일을 찾을 수 없습니다.")
        if not self.narrator_var.get().strip():
            problems.append("화자를 선택하세요.")
        if self.device_var.get() not in self.device_by_label:
            problems.append("VB-CABLE 출력 장치를 선택하세요.")
        if not self.api_key_var.get().strip():
            problems.append("OpenAI API 키를 입력하세요.")

        if problems:
            messagebox.showwarning("설정 점검", "\n".join(problems))
        else:
            messagebox.showinfo("설정 점검", "필수 설정이 모두 준비되었습니다.")

    def send_from_event(self, _event: tk.Event) -> str:
        self.send()
        return "break"

    def insert_newline(self, _event: tk.Event) -> str:
        self.input_text.insert("insert", "\n")
        return "break"

    def send(self) -> None:
        if self.busy:
            return
        user_text = self.input_text.get("1.0", "end-1c").strip()
        if not user_text:
            return

        api_key = self.api_key_var.get().strip()
        device_label = self.device_var.get()
        voicepeak = Path(self.voicepeak_var.get().strip())
        narrator = self.narrator_var.get().strip()

        if not api_key:
            messagebox.showwarning("API 키 필요", "OpenAI API 키를 입력하세요.")
            return
        if not voicepeak.is_file():
            messagebox.showwarning("VOICEPEAK", "올바른 voicepeak.exe를 선택하세요.")
            return
        if not narrator:
            messagebox.showwarning("VOICEPEAK", "화자를 선택하세요.")
            return
        if device_label not in self.device_by_label:
            messagebox.showwarning("VB-CABLE", "출력 장치를 선택하세요.")
            return

        self.input_text.delete("1.0", "end")
        self.append_message("프로듀서", user_text, "user")
        self.set_busy(True, "히나나가 생각하는 중입니다…")
        self.run_background(
            self.speak_worker,
            api_key,
            user_text,
            voicepeak,
            narrator,
            self.device_by_label[device_label],
            self.speed_var.get(),
            self.pitch_var.get(),
        )

    def speak_worker(
        self,
        api_key: str,
        user_text: str,
        voicepeak: Path,
        narrator: str,
        device: int,
        speed: int,
        pitch: int,
    ) -> None:
        try:
            client = OpenAI(api_key=api_key)
            answer = ask_llm(client, DEFAULT_MODEL, user_text)
            self.events.put(("answer", answer))
            self.events.put(("status", "VOICEPEAK 음성을 만드는 중입니다…"))

            with tempfile.TemporaryDirectory(prefix="hinana_voice_") as temp_dir:
                wav_paths = make_voicepeak_wavs(
                    voicepeak, narrator, answer, Path(temp_dir), speed, pitch
                )
                total = len(wav_paths)
                for index, wav_path in enumerate(wav_paths, start=1):
                    self.events.put(
                        ("status", f"Vocoflex로 재생하는 중입니다… ({index}/{total})")
                    )
                    candidates = playback_candidates(device)
                    used_device = play_to_device(wav_path, device, candidates)
                    if used_device != device:
                        used_name = sd.query_devices(used_device)["name"]
                        self.events.put(
                            (
                                "status",
                                f"오디오 장치 오류를 우회해 {used_device}번 "
                                f"({used_name})으로 재생합니다.",
                            )
                        )
            self.events.put(("done", "재생을 마쳤습니다."))
        except Exception as exc:
            self.events.put(("error_done", str(exc)))

    def append_message(self, speaker: str, text: str, tag: str) -> None:
        self.conversation.configure(state="normal")
        self.conversation.insert("end", f"{speaker}> {text}\n", tag)
        self.conversation.configure(state="disabled")
        self.conversation.see("end")

    def set_busy(self, busy: bool, status: str) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.send_button.configure(state=state)
        self.input_text.configure(state=state)
        self.status_var.set(status)
        if not busy:
            self.input_text.focus_set()

    def run_background(self, function, *args: object) -> None:
        threading.Thread(target=function, args=args, daemon=True).start()

    def poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "narrators":
                    names = list(payload)
                    self.narrator_combo["values"] = names
                    if self.narrator_var.get() not in names and names:
                        self.narrator_var.set(names[0])
                    self.status_var.set("VOICEPEAK 화자 목록을 불러왔습니다.")
                elif event == "answer":
                    self.append_message("히나나", str(payload), "assistant")
                elif event == "status":
                    self.status_var.set(str(payload))
                elif event == "done":
                    self.set_busy(False, str(payload))
                elif event == "error":
                    self.status_var.set(str(payload))
                    self.append_message("시스템", str(payload), "system")
                elif event == "error_done":
                    self.append_message("오류", str(payload), "system")
                    self.set_busy(False, "오류가 발생했습니다.")
        except queue.Empty:
            pass
        self.root.after(100, self.poll_events)

    def close(self) -> None:
        self.save_settings()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    HinanaVoiceApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
