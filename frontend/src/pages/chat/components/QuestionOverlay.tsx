import type { RefObject } from 'react';

import type { QuestionDialog } from '../../../shared/types';

export function QuestionOverlay({
  activeQuestion,
  questionAnswers,
  customAnswer,
  customInputRef,
  onToggleOption,
  onSelectCustomOption,
  onSetCustomAnswer,
  onCancel,
  onSubmit,
}: {
  activeQuestion: QuestionDialog | null;
  questionAnswers: string[];
  customAnswer: string;
  customInputRef: RefObject<HTMLTextAreaElement | null>;
  onToggleOption: (label: string) => void;
  onSelectCustomOption: () => void;
  onSetCustomAnswer: (value: string) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  if (!activeQuestion) {
    return null;
  }

  return (
    <div id="question-overlay" onClick={(event) => event.target === event.currentTarget && onCancel()}>
      <div className="question-card">
        <div className="q-header">{activeQuestion.header}</div>
        <div className="q-body">{activeQuestion.question}</div>
        <div className="q-options">
          {activeQuestion.options.map((option, index) => {
            const selected = questionAnswers.includes(option.label);
            return (
              <label
                key={`${option.label}-${index}`}
                className={`q-option ${selected ? 'selected' : ''}`}
                onClick={() => onToggleOption(option.label)}
              >
                <input
                  type={activeQuestion.multiple ? 'checkbox' : 'radio'}
                  name={`q-opt-${index}`}
                  checked={selected}
                  onChange={() => onToggleOption(option.label)}
                  onClick={(event) => event.stopPropagation()}
                />
                <span style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  <span className="q-label">{option.label}</span>
                  {option.description ? <span className="q-desc">{option.description}</span> : null}
                </span>
              </label>
            );
          })}

          <div className={`q-option ${questionAnswers.includes('__custom__') ? 'selected' : ''}`} onClick={onSelectCustomOption}>
            <input
              type="radio"
              name="q-custom"
              checked={questionAnswers.includes('__custom__')}
              onChange={onSelectCustomOption}
              onClick={(event) => event.stopPropagation()}
            />
            <span style={{ display: 'flex', flexDirection: 'column', gap: 1, flex: 1 }}>
              <span className="q-label">Custom (type your own answer)</span>
              {questionAnswers.includes('__custom__') ? (
                <textarea
                  ref={customInputRef}
                  value={customAnswer}
                  className="q-custom-input"
                  placeholder="Type your answer here..."
                  onChange={(event) => onSetCustomAnswer(event.target.value)}
                  onClick={(event) => event.stopPropagation()}
                />
              ) : null}
            </span>
          </div>
        </div>
        <div className="q-actions">
          <button className="q-btn cancel" onClick={onCancel}>
            Skip
          </button>
          <button className="q-btn submit" onClick={onSubmit}>
            Submit
          </button>
        </div>
      </div>
    </div>
  );
}
