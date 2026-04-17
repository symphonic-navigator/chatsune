# Mistral TTS / STT integration  

## Integration

`pnpm add @mistralai/mistralai`

Das ist das offizielle Typescript-SDK von Mistral AI.

## Initialisierung

```
// src/lib/mistral.ts
import { MistralClient } from "@mistralai/mistralai";

export const mistralClient = (apiKey: string) => {
  return new MistralClient({ apiKey });
};
```

## Text-To-Speech

```
// src/components/VoicePlayer.tsx
import { generateSpeech } from "../hooks/useTTS";

function VoicePlayer({ text, apiKey, voiceId }: { text: string; apiKey: string; voiceId?: string }) {
  const playSpeech = async () => {
    const audioBlob = await generateSpeech(text, apiKey, voiceId);
    const audioUrl = URL.createObjectURL(audioBlob);
    new Audio(audioUrl).play();
  };

  return <button onClick={playSpeech}>🔊 Play Voice</button>;
}
```

## Speech-To-Text

```
// src/components/VoiceRecorder.tsx
import { useState } from "react";
import { transcribeAudio } from "../hooks/useSTT";

function VoiceRecorder({ apiKey }: { apiKey: string }) {
  const [isRecording, setIsRecording] = useState(false);
  const [transcription, setTranscription] = useState("");

  const startRecording = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mediaRecorder = new MediaRecorder(stream);
    const audioChunks: Blob[] = [];

    mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
    mediaRecorder.onstop = async () => {
      const audioBlob = new Blob(audioChunks, { type: "audio/wav" });
      const file = new File([audioBlob], "recording.wav");
      const text = await transcribeAudio(file, apiKey);
      setTranscription(text);
    };

    mediaRecorder.start();
    setIsRecording(true);

    setTimeout(() => {
      mediaRecorder.stop();
      setIsRecording(false);
    }, 30000); // 30-second recording
  };

  return (
    <div>
      <button onClick={startRecording} disabled={isRecording}>
        {isRecording ? "⏹️ Recording..." : "🎤 Start Recording"}
      </button>
      {transcription && <p>Transcription: {transcription}</p>}
    </div>
  );
}
```

## Cloning

```
// src/components/VoiceCloner.tsx
import { useState } from "react";
import { cloneVoice } from "../hooks/useVoiceCloning";

function VoiceCloner({ apiKey }: { apiKey: string }) {
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [clonedVoiceId, setClonedVoiceId] = useState<string | null>(null);

  const startRecording = async () => {
    // Same recording logic as STT (see above)
    // After recording:
    const file = new File([audioBlob], "sample.wav");
    const cloned = await cloneVoice(file, apiKey, "My Custom Voice");
    setClonedVoiceId(cloned.voice_id);
  };

  return (
    <div>
      <h2>🎤 Clone a Voice</h2>
      <button onClick={startRecording}>Start Recording</button>
      {clonedVoiceId && (
        <p>Cloned voice ID: <code>{clonedVoiceId}</code></p>
      )}
    </div>
  );
}
```

## Error handling

```
try {
  const result = await cloneVoice(file, apiKey, "My Voice");
} catch (error) {
  const message = handleMistralError(error);
  alert(message);
}
```

## Get list of coices


```
// src/components/VoiceSettings.tsx
import { listVoices } from "../hooks/useVoices";

function VoiceSettings({ apiKey }: { apiKey: string }) {
  const [voices, setVoices] = useState([]);
  const [selectedVoice, setSelectedVoice] = useState("");

  useEffect(() => {
    listVoices(apiKey).then(setVoices);
  }, [apiKey]);

  return (
    <div>
      <h2>Stimmenauswahl</h2>
      <select
        value={selectedVoice}
        onChange={(e) => setSelectedVoice(e.target.value)}
      >
        {voices.map((voice) => (
          <option key={voice.voice_id} value={voice.voice_id}>
            {voice.name}
          </option>
        ))}
      </select>
      <button onClick={() => onSave(selectedVoice)}>Speichern</button>
    </div>
  );
}
```

## Use voice for TTS

```
// src/components/ChatWindow.tsx
import { generateSpeech } from "../hooks/useTTS";

function ChatWindow({ apiKey, voiceId }: { apiKey: string; voiceId: string }) {
  const playMessage = async (text: string) => {
    const audioBlob = await generateSpeech(text, apiKey, voiceId);
    const audioUrl = URL.createObjectURL(audioBlob);
    new Audio(audioUrl).play();
  };

  return (
    <div>
      <button onClick={() => playMessage("Hallo, wie kann ich helfen?")}>
        🔊 Nachricht abspielen
      </button>
    </div>
  );
}
```

## Delete cloned voice

```
async function deleteVoice(apiKey: string, voiceId: string) {
  const client = mistralClient(apiKey);
  await client.voices.delete(voiceId);
}
```

