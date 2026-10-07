/**
 * Web Speech API Voice Controller for STT (Speech-to-Text) and TTS (Text-to-Speech).
 * Full multi-lingual support including Indian languages.
 */

export interface SupportedLanguage {
  code: string;
  name: string;
  nativeName: string;
  speechCode: string;
}

export const SUPPORTED_LANGUAGES: SupportedLanguage[] = [
  { code: 'en', name: 'English', nativeName: 'English (India)', speechCode: 'en-IN' },
  { code: 'hi', name: 'Hindi', nativeName: 'हिन्दी', speechCode: 'hi-IN' },
  { code: 'mr', name: 'Marathi', nativeName: 'मराठी', speechCode: 'mr-IN' },
  { code: 'ta', name: 'Tamil', nativeName: 'தமிழ்', speechCode: 'ta-IN' },
  { code: 'te', name: 'Telugu', nativeName: 'తెలుగు', speechCode: 'te-IN' },
  { code: 'kn', name: 'Kannada', nativeName: 'ಕನ್ನಡ', speechCode: 'kn-IN' },
  { code: 'as', name: 'Assamese', nativeName: 'অসমীয়া', speechCode: 'as-IN' },
  { code: 'bn', name: 'Bengali', nativeName: 'বাংলা', speechCode: 'bn-IN' },
  { code: 'gu', name: 'Gujarati', nativeName: 'ગુજરાતી', speechCode: 'gu-IN' },
];

class VoiceController {
  private recognition: any = null;
  private isListening = false;
  private isSpeaking = false;
  private speechLang = 'en-IN';
  private currentUtterance: SpeechSynthesisUtterance | null = null;
  private availableVoices: SpeechSynthesisVoice[] = [];

  constructor() {
    if (typeof window !== 'undefined') {
      const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      if (SpeechRecognition) {
        this.recognition = new SpeechRecognition();
        this.recognition.continuous = false;
        this.recognition.interimResults = true;
        this.recognition.lang = 'en-IN';
      }

      if (window.speechSynthesis) {
        this.availableVoices = window.speechSynthesis.getVoices();
        window.speechSynthesis.onvoiceschanged = () => {
          this.availableVoices = window.speechSynthesis.getVoices();
        };
      }
    }
  }

  setLanguage(langCode: string) {
    const lang = SUPPORTED_LANGUAGES.find(l => l.code === langCode);
    this.speechLang = lang ? lang.speechCode : 'en-IN';
    if (this.recognition) {
      this.recognition.lang = this.speechLang;
    }
  }

  isSpeechSupported(): boolean {
    return !!this.recognition;
  }

  getIsSpeaking(): boolean {
    return this.isSpeaking;
  }

  getCurrentUtterance(): SpeechSynthesisUtterance | null {
    return this.currentUtterance;
  }

  getIsListening(): boolean {
    return this.isListening;
  }

  startListening(
    onResult: (transcript: string, isFinal: boolean) => void,
    onError?: (err: any) => void,
    onEnd?: () => void
  ) {
    if (!this.recognition) {
      if (onError) onError(new Error('Speech recognition not supported in this browser.'));
      return;
    }
    if (this.isListening) {
      this.stopListening();
    }

    this.recognition.lang = this.speechLang;
    this.isListening = true;

    this.recognition.onresult = (event: any) => {
      let interim = '';
      let final = '';
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          final += event.results[i][0].transcript;
        } else {
          interim += event.results[i][0].transcript;
        }
      }
      onResult(final || interim, !!final);
    };

    this.recognition.onerror = (event: any) => {
      this.isListening = false;
      if (onError) onError(event.error);
    };

    this.recognition.onend = () => {
      this.isListening = false;
      if (onEnd) onEnd();
    };

    try {
      this.recognition.start();
    } catch (e) {
      this.isListening = false;
    }
  }

  stopListening() {
    if (this.recognition && this.isListening) {
      this.recognition.stop();
      this.isListening = false;
    }
  }

  speak(text: string, onEnd?: () => void) {
    if (typeof window === 'undefined' || !window.speechSynthesis) return;

    this.stopSpeaking();

    // Clean markdown symbols for cleaner speech
    const cleanText = text
      .replace(/\[(?:Chunk|kg_triple|Entity):[^\]]+\]/g, '')
      .replace(/\[\d{1,3}\]/g, '')
      .replace(/\$\$?[^$]*\$\$?/g, '')
      .replace(/`{1,3}[^`]*`{1,3}/g, '')
      .replace(/[*_#>`]/g, '')
      .slice(0, 800); // Speak first 800 chars for concise spoken summary

    const utterance = new SpeechSynthesisUtterance(cleanText);
    utterance.lang = this.speechLang;
    utterance.rate = 1.0;
    utterance.pitch = 1.0;

    // Pick matching voice from cached list or freshly retrieved
    const voices = this.availableVoices.length > 0 ? this.availableVoices : window.speechSynthesis.getVoices();
    const matchingVoice = voices.find(v => v.lang.toLowerCase().replace('_', '-').startsWith(this.speechLang.slice(0, 2).toLowerCase()));
    if (matchingVoice) {
      utterance.voice = matchingVoice;
    }

    this.currentUtterance = utterance;
    this.isSpeaking = true;

    utterance.onend = () => {
      this.isSpeaking = false;
      this.currentUtterance = null;
      if (onEnd) onEnd();
    };

    utterance.onerror = () => {
      this.isSpeaking = false;
      this.currentUtterance = null;
      if (onEnd) onEnd();
    };

    if (window.speechSynthesis.paused) {
      window.speechSynthesis.resume();
    }
    window.speechSynthesis.speak(utterance);
  }

  stopSpeaking() {
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel();
      this.currentUtterance = null;
      this.isSpeaking = false;
    }
  }
}

export const voiceController = new VoiceController();
