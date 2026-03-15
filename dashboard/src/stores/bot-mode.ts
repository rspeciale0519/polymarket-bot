import { create } from "zustand";

interface BotModeStore {
  mode: "paper" | "live";
  connected: boolean;
  isRunning: boolean;
  isPaused: boolean;
  setMode: (mode: "paper" | "live") => void;
  setConnected: (connected: boolean) => void;
  setIsRunning: (running: boolean) => void;
  setIsPaused: (paused: boolean) => void;
  updateFromOverview: (data: {
    mode: string;
    connected: boolean;
    isRunning: boolean;
    isPaused: boolean;
  }) => void;
}

export const useBotMode = create<BotModeStore>((set) => ({
  mode: "paper",
  connected: false,
  isRunning: false,
  isPaused: false,
  setMode: (mode) => set({ mode }),
  setConnected: (connected) => set({ connected }),
  setIsRunning: (isRunning) => set({ isRunning }),
  setIsPaused: (isPaused) => set({ isPaused }),
  updateFromOverview: (data) =>
    set({
      mode: data.mode === "live" ? "live" : "paper",
      connected: data.connected,
      isRunning: data.isRunning,
      isPaused: data.isPaused,
    }),
}));
