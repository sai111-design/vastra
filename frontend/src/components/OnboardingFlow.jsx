import { useState, useCallback } from 'react';

const VIBES = [
  { id: 'minimal', emoji: '⚪', label: 'Minimal', desc: 'Clean lines, neutral tones' },
  { id: 'streetwear', emoji: '🧢', label: 'Streetwear', desc: 'Bold, oversized, graphic' },
  { id: 'ethnic', emoji: '🪔', label: 'Ethnic Fusion', desc: 'Indian-inspired, festive' },
  { id: 'casual', emoji: '👕', label: 'Casual Everyday', desc: 'Comfort-first, relaxed' },
];

const BUDGETS = [
  { id: 'under_500', label: 'Under ₹500' },
  { id: '500_1500', label: '₹500 – ₹1500' },
  { id: 'above_1500', label: '₹1500+' },
];

const CATEGORIES = [
  { id: 'tops', label: 'Tops' },
  { id: 'bottoms', label: 'Bottoms' },
  { id: 'dresses', label: 'Dresses' },
  { id: 'footwear', label: 'Footwear' },
  { id: 'accessories', label: 'Accessories' },
  { id: 'surprise_me', label: 'Surprise me' },
];

const TITLES = {
  1: { title: "What's your style?", subtitle: "Pick the vibe that feels most like you." },
  2: { title: "What's your budget?", subtitle: "Helps me filter picks to your range." },
  3: { title: "Today's mission?", subtitle: "Pick anything that fits — or hit Surprise me." },
};

export default function OnboardingFlow({ onComplete, onSkip }) {
  const [step, setStep] = useState(1);
  const [vibe, setVibe] = useState(null);
  const [budget, setBudget] = useState(null);
  const [categories, setCategories] = useState([]);

  const toggleCategory = useCallback((id) => {
    setCategories(prev => {
      if (id === 'surprise_me') {
        return prev.includes('surprise_me') ? [] : ['surprise_me'];
      }
      const without = prev.filter(c => c !== 'surprise_me');
      return without.includes(id) ? without.filter(c => c !== id) : [...without, id];
    });
  }, []);

  const canContinue = (
    (step === 1 && vibe !== null) ||
    (step === 2 && budget !== null) ||
    (step === 3 && categories.length > 0)
  );

  const handleContinue = () => {
    if (!canContinue) return;
    if (step < 3) {
      setStep(step + 1);
    } else {
      onComplete({ vibe, budget, categories });
    }
  };

  const handleBack = () => {
    if (step > 1) setStep(step - 1);
  };

  const t = TITLES[step];

  return (
    <div className="onboarding-overlay" role="dialog" aria-label="Welcome to vastra">
      <div className="onboarding-card">
        <div className="onboarding-progress" aria-label={`Step ${step} of 3`}>
          {[1, 2, 3].map(i => (
            <span
              key={i}
              className={`onboarding-dot${i === step ? ' active' : ''}`}
              aria-current={i === step ? 'step' : undefined}
            />
          ))}
        </div>

        <div className="onboarding-head">
          {step > 1 && (
            <button
              type="button"
              className="onboarding-back"
              onClick={handleBack}
              aria-label="Back"
            >
              ‹
            </button>
          )}
          <div className="onboarding-head-text">
            <div className="onboarding-title">{t.title}</div>
            <div className="onboarding-subtitle">{t.subtitle}</div>
          </div>
        </div>

        {step === 1 && (
          <div className="vibe-grid" role="radiogroup" aria-label="Style vibe">
            {VIBES.map(v => (
              <button
                key={v.id}
                type="button"
                role="radio"
                aria-checked={vibe === v.id}
                className={`vibe-tile${vibe === v.id ? ' selected' : ''}`}
                onClick={() => setVibe(v.id)}
              >
                <div className="vibe-emoji" aria-hidden="true">{v.emoji}</div>
                <div className="vibe-label">{v.label}</div>
                <div className="vibe-desc">{v.desc}</div>
              </button>
            ))}
          </div>
        )}

        {step === 2 && (
          <div className="budget-options" role="radiogroup" aria-label="Budget">
            {BUDGETS.map(b => (
              <button
                key={b.id}
                type="button"
                role="radio"
                aria-checked={budget === b.id}
                className={`budget-option${budget === b.id ? ' selected' : ''}`}
                onClick={() => setBudget(b.id)}
              >
                {b.label}
              </button>
            ))}
          </div>
        )}

        {step === 3 && (
          <div className="category-grid" role="group" aria-label="Shopping categories">
            {CATEGORIES.map(c => (
              <button
                key={c.id}
                type="button"
                aria-pressed={categories.includes(c.id)}
                className={`category-chip-onboard${categories.includes(c.id) ? ' selected' : ''}`}
                onClick={() => toggleCategory(c.id)}
              >
                {c.label}
              </button>
            ))}
          </div>
        )}

        <button
          type="button"
          className="onboarding-continue"
          onClick={handleContinue}
          disabled={!canContinue}
        >
          {step < 3 ? 'Continue' : 'Start shopping'}
        </button>
        <button
          type="button"
          className="onboarding-skip"
          onClick={onSkip}
        >
          Skip for now
        </button>
      </div>
    </div>
  );
}
