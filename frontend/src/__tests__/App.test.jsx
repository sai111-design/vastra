import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import '@testing-library/jest-dom';
import App from '../App';
import * as useChatStreamModule from '../hooks/useChatStream';

// Mock the scrollIntoView which is missing in jsdom
window.HTMLElement.prototype.scrollIntoView = vi.fn();

describe('App component', () => {
  beforeEach(() => {
    // App renders the OnboardingFlow modal when vastra_onboarded isn't set,
    // which would shadow the empty-state assertions below. Treat onboarding
    // as already complete unless a test opts back in.
    window.localStorage.setItem('vastra_onboarded', '1');
  });

  it('renders loading state initially', () => {
    // Spy on useChatStream to return default unready state
    vi.spyOn(useChatStreamModule, 'default').mockReturnValue({
      appReady: false,
    });

    render(<App />);
    expect(screen.getByText(/Waking up the store/i)).toBeInTheDocument();
  });

  it('renders chat empty state when ready without session', () => {
    vi.spyOn(useChatStreamModule, 'default').mockReturnValue({
      appReady: true,
      currentSessionId: null,
      messages: [],
      sessions: [],
      cart: null,
      pendingConfirm: null,
      isStreaming: false,
      suggestions: [],
      shelfProducts: [],
      buyerProfile: null,
      dismissedOutfitPrompts: new Set(),
      createSession: vi.fn(),
      openSession: vi.fn(),
      sendMessage: vi.fn(),
      goBack: vi.fn(),
      toggleCart: vi.fn(),
      clearSuggestions: vi.fn(),
      confirmAction: vi.fn(),
      dismissOutfitPrompt: vi.fn(),
    });

    render(<App />);
    expect(screen.getByText(/Pick a chat or start fresh/i)).toBeInTheDocument();
  });
});
