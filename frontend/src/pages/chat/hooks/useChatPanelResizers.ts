import { useCallback, useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type RefObject } from 'react';

const SIDEBAR_WIDTH_STORAGE_KEY = 'sidebar-width';
const MIN_SIDEBAR_WIDTH = 200;
const MAX_SIDEBAR_WIDTH = 520;
const DEFAULT_SIDEBAR_WIDTH = 280;
const WORKSPACE_WIDTH_STORAGE_KEY = 'workspace-width';
const MIN_WORKSPACE_WIDTH = 240;
const MAX_WORKSPACE_WIDTH = 560;
const DEFAULT_WORKSPACE_WIDTH = 320;
const PLAN_DOCS_HEIGHT_STORAGE_KEY = 'plan-docs-height';
const MIN_PLAN_DOCS_HEIGHT = 120;
const MIN_MODIFIED_FILES_HEIGHT = 140;
const DEFAULT_PLAN_DOCS_HEIGHT = 220;
const WORKSPACE_SECTION_RESIZER_SIZE = 6;
const INPUT_AREA_HEIGHT_STORAGE_KEY = 'input-area-height';
const MIN_INPUT_AREA_HEIGHT = 180;
const DEFAULT_INPUT_AREA_HEIGHT = 200;
const INPUT_AREA_RESIZER_SIZE = 6;
const MIN_CHAT_HEIGHT = 180;
const MAX_STORED_PANEL_HEIGHT = 2000;

function readStoredDimension(storageKey: string, minValue: number, maxValue: number, defaultValue: number): number {
  const stored = Number(localStorage.getItem(storageKey));
  if (Number.isFinite(stored) && stored >= minValue && stored <= maxValue) {
    return stored;
  }
  return defaultValue;
}

function readStoredSidebarWidth(): number {
  return readStoredDimension(SIDEBAR_WIDTH_STORAGE_KEY, MIN_SIDEBAR_WIDTH, MAX_SIDEBAR_WIDTH, DEFAULT_SIDEBAR_WIDTH);
}

function readStoredWorkspaceWidth(): number {
  return readStoredDimension(WORKSPACE_WIDTH_STORAGE_KEY, MIN_WORKSPACE_WIDTH, MAX_WORKSPACE_WIDTH, DEFAULT_WORKSPACE_WIDTH);
}

function readStoredPlanDocsHeight(): number {
  return readStoredDimension(PLAN_DOCS_HEIGHT_STORAGE_KEY, MIN_PLAN_DOCS_HEIGHT, MAX_STORED_PANEL_HEIGHT, DEFAULT_PLAN_DOCS_HEIGHT);
}

function readStoredInputAreaHeight(): number {
  return readStoredDimension(INPUT_AREA_HEIGHT_STORAGE_KEY, MIN_INPUT_AREA_HEIGHT, MAX_STORED_PANEL_HEIGHT, DEFAULT_INPUT_AREA_HEIGHT);
}

export function useChatPanelResizers({
  mainPanelRef,
  chatHeaderRef,
  streamingIndicatorRef,
  workspacePanelRef,
  isStreaming,
}: {
  mainPanelRef: RefObject<HTMLDivElement | null>;
  chatHeaderRef: RefObject<HTMLDivElement | null>;
  streamingIndicatorRef: RefObject<HTMLDivElement | null>;
  workspacePanelRef: RefObject<HTMLElement | null>;
  isStreaming: boolean;
}) {
  const [sidebarWidth, setSidebarWidth] = useState(readStoredSidebarWidth);
  const [isResizing, setIsResizing] = useState(false);
  const resizeStateRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const [workspaceWidth, setWorkspaceWidth] = useState(readStoredWorkspaceWidth);
  const [isWorkspaceResizing, setIsWorkspaceResizing] = useState(false);
  const workspaceResizeStateRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const [planDocsHeight, setPlanDocsHeight] = useState(readStoredPlanDocsHeight);
  const [isPlanDocsResizing, setIsPlanDocsResizing] = useState(false);
  const planDocsResizeStateRef = useRef<{ startY: number; startHeight: number } | null>(null);
  const [inputAreaHeight, setInputAreaHeight] = useState(readStoredInputAreaHeight);
  const [isInputAreaResizing, setIsInputAreaResizing] = useState(false);
  const inputAreaResizeStateRef = useRef<{ startY: number; startHeight: number } | null>(null);

  const clampPlanDocsHeight = useCallback((height: number) => {
    const containerHeight = workspacePanelRef.current?.clientHeight;
    if (!containerHeight) {
      return Math.max(MIN_PLAN_DOCS_HEIGHT, height);
    }
    const maxHeight = Math.max(0, containerHeight - MIN_MODIFIED_FILES_HEIGHT - WORKSPACE_SECTION_RESIZER_SIZE);
    const minHeight = Math.min(MIN_PLAN_DOCS_HEIGHT, maxHeight);
    return Math.min(maxHeight, Math.max(minHeight, height));
  }, [workspacePanelRef]);

  const clampInputAreaHeight = useCallback((height: number) => {
    const containerHeight = mainPanelRef.current?.clientHeight;
    if (!containerHeight) {
      return Math.max(MIN_INPUT_AREA_HEIGHT, height);
    }
    const headerHeight = chatHeaderRef.current?.offsetHeight ?? 0;
    const streamingHeight = streamingIndicatorRef.current?.offsetHeight ?? 0;
    const maxHeight = Math.max(0, containerHeight - headerHeight - streamingHeight - MIN_CHAT_HEIGHT - INPUT_AREA_RESIZER_SIZE);
    const minHeight = Math.min(MIN_INPUT_AREA_HEIGHT, maxHeight);
    return Math.min(maxHeight, Math.max(minHeight, height));
  }, [chatHeaderRef, mainPanelRef, streamingIndicatorRef]);

  const handleResizeMove = useCallback((event: MouseEvent) => {
    const state = resizeStateRef.current;
    if (!state) {
      return;
    }
    const delta = event.clientX - state.startX;
    const nextWidth = Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, state.startWidth + delta));
    setSidebarWidth(nextWidth);
  }, []);

  const handleResizeEnd = useCallback(() => {
    resizeStateRef.current = null;
    setIsResizing(false);
    document.body.style.removeProperty('cursor');
    document.body.style.removeProperty('user-select');
    window.removeEventListener('mousemove', handleResizeMove);
    window.removeEventListener('mouseup', handleResizeEnd);
    setSidebarWidth((current) => {
      localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(current));
      return current;
    });
  }, [handleResizeMove]);

  const handleResizeStart = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      event.preventDefault();
      resizeStateRef.current = { startX: event.clientX, startWidth: sidebarWidth };
      setIsResizing(true);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      window.addEventListener('mousemove', handleResizeMove);
      window.addEventListener('mouseup', handleResizeEnd);
    },
    [handleResizeEnd, handleResizeMove, sidebarWidth],
  );

  const handleWorkspaceResizeMove = useCallback((event: MouseEvent) => {
    const state = workspaceResizeStateRef.current;
    if (!state) {
      return;
    }
    const delta = event.clientX - state.startX;
    const nextWidth = Math.min(MAX_WORKSPACE_WIDTH, Math.max(MIN_WORKSPACE_WIDTH, state.startWidth - delta));
    setWorkspaceWidth(nextWidth);
  }, []);

  const handleWorkspaceResizeEnd = useCallback(() => {
    workspaceResizeStateRef.current = null;
    setIsWorkspaceResizing(false);
    document.body.style.removeProperty('cursor');
    document.body.style.removeProperty('user-select');
    window.removeEventListener('mousemove', handleWorkspaceResizeMove);
    window.removeEventListener('mouseup', handleWorkspaceResizeEnd);
    setWorkspaceWidth((current) => {
      localStorage.setItem(WORKSPACE_WIDTH_STORAGE_KEY, String(current));
      return current;
    });
  }, [handleWorkspaceResizeMove]);

  const handleWorkspaceResizeStart = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      event.preventDefault();
      workspaceResizeStateRef.current = { startX: event.clientX, startWidth: workspaceWidth };
      setIsWorkspaceResizing(true);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      window.addEventListener('mousemove', handleWorkspaceResizeMove);
      window.addEventListener('mouseup', handleWorkspaceResizeEnd);
    },
    [handleWorkspaceResizeEnd, handleWorkspaceResizeMove, workspaceWidth],
  );

  const handlePlanDocsResizeMove = useCallback((event: MouseEvent) => {
    const state = planDocsResizeStateRef.current;
    if (!state) {
      return;
    }
    const delta = event.clientY - state.startY;
    setPlanDocsHeight(clampPlanDocsHeight(state.startHeight - delta));
  }, [clampPlanDocsHeight]);

  const handlePlanDocsResizeEnd = useCallback(() => {
    planDocsResizeStateRef.current = null;
    setIsPlanDocsResizing(false);
    document.body.style.removeProperty('cursor');
    document.body.style.removeProperty('user-select');
    window.removeEventListener('mousemove', handlePlanDocsResizeMove);
    window.removeEventListener('mouseup', handlePlanDocsResizeEnd);
    setPlanDocsHeight((current) => {
      const next = clampPlanDocsHeight(current);
      localStorage.setItem(PLAN_DOCS_HEIGHT_STORAGE_KEY, String(next));
      return next;
    });
  }, [clampPlanDocsHeight, handlePlanDocsResizeMove]);

  const handlePlanDocsResizeStart = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      event.preventDefault();
      planDocsResizeStateRef.current = { startY: event.clientY, startHeight: planDocsHeight };
      setIsPlanDocsResizing(true);
      document.body.style.cursor = 'row-resize';
      document.body.style.userSelect = 'none';
      window.addEventListener('mousemove', handlePlanDocsResizeMove);
      window.addEventListener('mouseup', handlePlanDocsResizeEnd);
    },
    [handlePlanDocsResizeEnd, handlePlanDocsResizeMove, planDocsHeight],
  );

  const handleInputAreaResizeMove = useCallback((event: MouseEvent) => {
    const state = inputAreaResizeStateRef.current;
    if (!state) {
      return;
    }
    const delta = event.clientY - state.startY;
    setInputAreaHeight(clampInputAreaHeight(state.startHeight - delta));
  }, [clampInputAreaHeight]);

  const handleInputAreaResizeEnd = useCallback(() => {
    inputAreaResizeStateRef.current = null;
    setIsInputAreaResizing(false);
    document.body.style.removeProperty('cursor');
    document.body.style.removeProperty('user-select');
    window.removeEventListener('mousemove', handleInputAreaResizeMove);
    window.removeEventListener('mouseup', handleInputAreaResizeEnd);
    setInputAreaHeight((current) => {
      const next = clampInputAreaHeight(current);
      localStorage.setItem(INPUT_AREA_HEIGHT_STORAGE_KEY, String(next));
      return next;
    });
  }, [clampInputAreaHeight, handleInputAreaResizeMove]);

  const handleInputAreaResizeStart = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      event.preventDefault();
      inputAreaResizeStateRef.current = { startY: event.clientY, startHeight: inputAreaHeight };
      setIsInputAreaResizing(true);
      document.body.style.cursor = 'row-resize';
      document.body.style.userSelect = 'none';
      window.addEventListener('mousemove', handleInputAreaResizeMove);
      window.addEventListener('mouseup', handleInputAreaResizeEnd);
    },
    [handleInputAreaResizeEnd, handleInputAreaResizeMove, inputAreaHeight],
  );

  useEffect(() => {
    return () => {
      window.removeEventListener('mousemove', handleResizeMove);
      window.removeEventListener('mouseup', handleResizeEnd);
      window.removeEventListener('mousemove', handleWorkspaceResizeMove);
      window.removeEventListener('mouseup', handleWorkspaceResizeEnd);
      window.removeEventListener('mousemove', handlePlanDocsResizeMove);
      window.removeEventListener('mouseup', handlePlanDocsResizeEnd);
      window.removeEventListener('mousemove', handleInputAreaResizeMove);
      window.removeEventListener('mouseup', handleInputAreaResizeEnd);
    };
  }, [handleInputAreaResizeEnd, handleInputAreaResizeMove, handlePlanDocsResizeEnd, handlePlanDocsResizeMove, handleResizeEnd, handleResizeMove, handleWorkspaceResizeEnd, handleWorkspaceResizeMove]);

  useEffect(() => {
    const syncPlanDocsHeight = () => {
      setPlanDocsHeight((current) => clampPlanDocsHeight(current));
    };
    syncPlanDocsHeight();
    window.addEventListener('resize', syncPlanDocsHeight);
    return () => {
      window.removeEventListener('resize', syncPlanDocsHeight);
    };
  }, [clampPlanDocsHeight]);

  useEffect(() => {
    setInputAreaHeight((current) => clampInputAreaHeight(current));
  }, [clampInputAreaHeight, isStreaming]);

  useEffect(() => {
    const syncInputAreaHeight = () => {
      setInputAreaHeight((current) => clampInputAreaHeight(current));
    };
    syncInputAreaHeight();
    window.addEventListener('resize', syncInputAreaHeight);
    return () => {
      window.removeEventListener('resize', syncInputAreaHeight);
    };
  }, [clampInputAreaHeight]);

  const resetSidebarWidth = useCallback(() => {
    setSidebarWidth(DEFAULT_SIDEBAR_WIDTH);
    localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(DEFAULT_SIDEBAR_WIDTH));
  }, []);

  const resetWorkspaceWidth = useCallback(() => {
    setWorkspaceWidth(DEFAULT_WORKSPACE_WIDTH);
    localStorage.setItem(WORKSPACE_WIDTH_STORAGE_KEY, String(DEFAULT_WORKSPACE_WIDTH));
  }, []);

  const resetPlanDocsHeight = useCallback(() => {
    const next = clampPlanDocsHeight(DEFAULT_PLAN_DOCS_HEIGHT);
    setPlanDocsHeight(next);
    localStorage.setItem(PLAN_DOCS_HEIGHT_STORAGE_KEY, String(next));
  }, [clampPlanDocsHeight]);

  const resetInputAreaHeight = useCallback(() => {
    const next = clampInputAreaHeight(DEFAULT_INPUT_AREA_HEIGHT);
    setInputAreaHeight(next);
    localStorage.setItem(INPUT_AREA_HEIGHT_STORAGE_KEY, String(next));
  }, [clampInputAreaHeight]);

  return {
    sidebarWidth,
    workspaceWidth,
    planDocsHeight,
    inputAreaHeight,
    isResizing,
    isWorkspaceResizing,
    isPlanDocsResizing,
    isInputAreaResizing,
    handleResizeStart,
    handleWorkspaceResizeStart,
    handlePlanDocsResizeStart,
    handleInputAreaResizeStart,
    resetSidebarWidth,
    resetWorkspaceWidth,
    resetPlanDocsHeight,
    resetInputAreaHeight,
  };
}
