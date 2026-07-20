import { create } from "zustand";

interface SidebarState {
  currentPageId: string | null;
  setCurrentPageId: (currentPageId: string | null) => void;
}

export const useSidebarStore = create<SidebarState>()((set) => ({
  currentPageId: null,
  setCurrentPageId: (currentPageId) => set(() => ({ currentPageId })),
}));
