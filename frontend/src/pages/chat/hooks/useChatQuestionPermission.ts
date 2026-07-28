import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';

import type { PermissionRequest, QuestionDialog } from '../../../shared/types';

export function useChatQuestionPermission({ customInputRef }: { customInputRef: RefObject<HTMLTextAreaElement | null> }) {
  const [activeQuestion, setActiveQuestion] = useState<QuestionDialog | null>(null);
  const [questionAnswers, setQuestionAnswers] = useState<string[]>([]);
  const [customAnswer, setCustomAnswer] = useState('');
  const [activePermission, setActivePermission] = useState<PermissionRequest | null>(null);
  const activeQuestionRef = useRef<QuestionDialog | null>(activeQuestion);
  const questionQueueRef = useRef<QuestionDialog[]>([]);

  useEffect(() => {
    activeQuestionRef.current = activeQuestion;
  }, [activeQuestion]);

  const resetQuestionState = useCallback(() => {
    setQuestionAnswers([]);
    setCustomAnswer('');
  }, []);

  const showNextOrCloseQuestion = useCallback(() => {
    const nextQuestion = questionQueueRef.current.shift() ?? null;
    setActiveQuestion(nextQuestion);
    resetQuestionState();
  }, [resetQuestionState]);

  const resetInteractionState = useCallback((resetFlowState: () => void) => {
    resetFlowState();
    setActivePermission(null);
    setActiveQuestion(null);
    resetQuestionState();
    questionQueueRef.current = [];
  }, [resetQuestionState]);

  const enqueueQuestion = useCallback((payload: QuestionDialog) => {
    if (activeQuestionRef.current === null) {
      setActiveQuestion(payload);
      resetQuestionState();
    } else {
      questionQueueRef.current.push(payload);
    }
  }, [resetQuestionState]);

  const receivePermissionRequest = useCallback((payload: PermissionRequest) => {
    if (activeQuestionRef.current !== null) {
      questionQueueRef.current.unshift(activeQuestionRef.current);
      setActiveQuestion(null);
      resetQuestionState();
    }
    setActivePermission(payload);
  }, [resetQuestionState]);

  const clearAfterStreamDone = useCallback(() => {
    setActivePermission(null);
    questionQueueRef.current = [];
  }, []);

  const clearPermission = useCallback(() => {
    setActivePermission(null);
    if (questionQueueRef.current.length > 0) {
      const nextQuestion = questionQueueRef.current.shift() ?? null;
      setActiveQuestion(nextQuestion);
      resetQuestionState();
    }
  }, [resetQuestionState]);

  const sendPermissionDecision = useCallback(async (decision: 'allow' | 'deny' | 'allow_always') => {
    try {
      await fetch('/api/permission-response', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision }),
      });
    } catch {
      // Best-effort only; the backend manages timeout fallback.
    }
    clearPermission();
  }, [clearPermission]);

  const permissionDeny = useCallback(() => void sendPermissionDecision('deny'), [sendPermissionDecision]);
  const permissionAllow = useCallback(() => void sendPermissionDecision('allow'), [sendPermissionDecision]);
  const permissionAlwaysAllow = useCallback(() => void sendPermissionDecision('allow_always'), [sendPermissionDecision]);

  const toggleQuestionOption = useCallback((label: string) => {
    setQuestionAnswers((prev) => {
      if (activeQuestionRef.current?.multiple) {
        return prev.includes(label) ? prev.filter((entry) => entry !== label) : [...prev, label];
      }
      return [label];
    });
  }, []);

  const selectCustomOption = useCallback(() => {
    setQuestionAnswers(['__custom__']);
    window.requestAnimationFrame(() => {
      customInputRef.current?.focus();
    });
  }, [customInputRef]);

  const submitQuestion = useCallback(async () => {
    let answer = questionAnswers;
    if (answer.includes('__custom__')) {
      answer = [customAnswer.trim() || '(skipped)'];
    }
    if (answer.length === 0) {
      answer = ['(skipped)'];
    }

    await fetch('/api/question-answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer }),
    });
    showNextOrCloseQuestion();
  }, [customAnswer, questionAnswers, showNextOrCloseQuestion]);

  const cancelQuestion = useCallback(() => {
    void fetch('/api/question-answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer: ['(skipped)'] }),
    });
    showNextOrCloseQuestion();
  }, [showNextOrCloseQuestion]);

  return {
    activeQuestion,
    questionAnswers,
    customAnswer,
    activePermission,
    setCustomAnswer,
    toggleQuestionOption,
    selectCustomOption,
    submitQuestion,
    cancelQuestion,
    permissionDeny,
    permissionAllow,
    permissionAlwaysAllow,
    enqueueQuestion,
    receivePermissionRequest,
    clearAfterStreamDone,
    resetInteractionState,
  };
}
