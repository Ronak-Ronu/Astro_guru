A production-ready AI astrology bot built on WhatsApp that delivers personalized horoscopes and birth chart analyses. The system integrates real-time planetary data from NASA JPL Horizons API with a Mistral-7B LLM (4-bit quantized) to generate context‑aware, personalized horoscope content. It handles multi‑turn conversations with end‑to‑end response times under 30 seconds.


[Tech design](https://docs.google.com/document/d/1H43NbVBOfQAlz71suctGZuWnRGQ8Hke6esLMjvgc93I/edit?tab=t.0)
## Technology Stack & Architecture
The solution is architected as scalable microservices to support 10,000+ concurrent users:

API Gateway – Kong for rate limiting, routing, and authentication.

Backend Services –

Spring Boot for core business logic and user management.

FastAPI serving as a LangChain orchestration layer for LLM interactions.

Data Layer –

PostgreSQL for relational data (users, subscriptions, chat history).

Redis for caching and session management.

Pinecone as a vector database for context retrieval and memory.

Optimizations – Caching strategies and asynchronous processing ensure low latency and high throughput.

## Payment & Monetization
Fully integrated payment flow via WhatsApp Business API + Stripe:

Tiered subscription plans: ₹9 (basic) and ₹49 (premium).

Usage tracking and webhook‑based premium activation upon successful payment.

Designed to achieve a 15%+ conversion rate by delivering immediate value through the chat interface.

## Performance
Planetary data fetched in real time from NASA JPL Horizons.

Horoscope generation powered by a quantized Mistral‑7B model running efficiently on GPU instances.

Multi‑turn conversation handling with sub‑30 second response times even under load.