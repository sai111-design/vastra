# Vastra Demo Script (2-Minute Video)

This script is designed to record a tight, 2-minute demonstration of Vastra's core capabilities. Keep a brisk pace while allowing a few seconds for the LLM to stream responses.

## Setup
1. Ensure the backend and frontend are running (`uvicorn` and `npm run dev` or the Docker container).
2. Open the browser to the frontend (e.g., `http://localhost:5173`).
3. Start recording your screen.

## 0:00 - 0:10 | Introduction & Discovery
* **Action**: Create a new conversation and send the first message: 
  > "I'm looking for a solid color t-shirt under ₹500."
* **Speaking Notes**: "This is Vastra, a conversational commerce agent for Shopify. Here, the Supervisor routes our request to the Stylist agent, which queries the Shopify MCP and returns live products."
* **Visual**: The agent replies with product cards displaying real images, variants, and prices.

## 0:10 - 0:30 | Multi-turn Refinement & Context
* **Action**: Send a follow-up:
  > "Do you have the classic tee in blue?"
* **Speaking Notes**: "The agent maintains context across turns. It drops the price constraint, searches for blue t-shirts, and shows the updated catalog."
* **Visual**: Updated product cards.

## 0:30 - 0:55 | The Cart Write-Gate (Safety feature)
* **Action**: Send the message:
  > "Add the blue one in size Medium to my cart."
* **Speaking Notes**: "When we try to modify the cart, the Supervisor routes to the Cart agent. Notice the agent pauses and asks for confirmation. This is LangGraph's interrupt feature preventing unapproved writes to the checkout state."
* **Action**: Click the **Confirm** button in the chat chip.
* **Visual**: The cart drawer slides open, showing the item added and the updated subtotal.

## 0:55 - 1:20 | Support & Policy (Grounding)
* **Action**: Close the cart and ask:
  > "What is your return policy?"
* **Speaking Notes**: "Here, the Supervisor detects a policy query and routes it to the Support agent. The agent uses the MCP to fetch the real shop policies, strictly grounding its answer and citing the exact section."
* **Visual**: Agent replies with the 7-day return policy.

## 1:20 - 1:40 | Preference Extraction
* **Action**: In the same conversation, send:
  > "What else would go with this?"
* **Speaking Notes**: "Behind the scenes, a lightweight Llama 3.1 8B model runs after each reply to extract preferences — sizes, budget, style tags, last category — into a `buyer_profiles` row keyed on the session. Subsequent turns in this session inherit that profile silently, so suggestions stay grounded in what we've already said we want."
* **Visual**: Agent suggests complementary items biased toward size M and the established budget.

## 1:40 - 2:00 | Checkout Handoff
* **Action**: Send:
  > "Show my cart."
* **Speaking Notes**: "The cart state is retrieved directly from Shopify via the MCP. From here, the user can click 'Checkout' and be directed straight to the secure Shopify checkout page with their items pre-loaded."
* **Action**: Click the **Checkout** button in the banner or cart drawer.
* **Visual**: Redirect to the Shopify checkout screen. (End video).
