A production-ready AI astrology bot built on WhatsApp that delivers personalized horoscopes and birth chart analyses. The system integrates real-time planetary data from NASA JPL Horizons API with a Mistral-7B LLM (4-bit quantized) to generate context‑aware, personalized horoscope content. It handles multi‑turn conversations with end‑to‑end response times under 30 seconds.


[Tech design](https://docs.google.com/document/d/1H43NbVBOfQAlz71suctGZuWnRGQ8Hke6esLMjvgc93I/edit?tab=t.0)
## Technology Stack & Architecture
# Astro App

##  Architecture

### Core Components

#### 1. FastAPI Application (`main.py`)
- **Main entry point for the application**:
  - Handles HTTP endpoints and WhatsApp webhooks.
  - Manages user sessions and message processing.

#### 2. Services Layer

##### Astrology Services (`/app/services/astrology/`)
- **`chart_calculations.py`**: Natal chart and transit calculations using Swiss Ephemeris.
- **`synastry_flow.py`**: Compatibility analysis between two individuals.

##### Cloudflare Integration (`/app/services/cloudflare/`)
- **`d1_client.py`**: D1 database client for serverless SQL operations.
- **`users_service.py`**: User management and profile operations.
- **`payments_service.py`**: Payment record management.
- **`feedback_service.py`**: User feedback collection.
- **`synastry_service.py`**: Compatibility data persistence.

##### WhatsApp Integration (`/app/services/whatsapp/`)
- **`send_messageAndEvents.py`**: WhatsApp Business API message handling.
- **`payments.py`**: UPI intent payment message handling.
- **Interactive message templates and reactions**.

##### ChromaDB Integration (`/app/services/chroma_cloud/`)
- **Vector database**: For storing astrological knowledge.
- **RAG (Retrieval-Augmented Generation)**: For contextual responses.

#### 3. Utility Modules (`/app/util/`)
- **`natal_chart/send_chart.py`**: PDF generation for natal charts.
- **`CTA_buttons_NLP/buttons_nlp.py`**: Dynamic button generation based on context.

#### 4. Configuration (`/app/config/`)
- **`settings.py`**: Environment variables and app settings.
- **`constants.py`**: Application constants, prompts, payment plans.

---

##  Technical Stack

### Core Framework
- **FastAPI**: Web framework.
- **Uvicorn**: ASGI server.

### AI/ML Components
- **Sentence Transformers (`all-MiniLM-L6-v2`)**: Embedding generation.
- **LangChain**: RAG pipeline and vector store management.
- **ChromaDB**: Vector database for knowledge retrieval.
- **HuggingFace Embeddings**: Alternative embedding provider.

### Astrology Libraries
- **Swiss Ephemeris (`swisseph`)**: Planetary calculations.
- **Kerykeion**: Astrological chart calculations.
- **TimezoneFinder**: Timezone detection from coordinates.

### Database & Storage
- **Cloudflare D1**: Serverless SQL database.
- **Cloudflare Workers**: AI service endpoints.
- **ChromaDB**: Vector storage (local/cloud).

### External APIs
- **WhatsApp Business API**: Messaging platform.
- **Cloudflare Workers**: Custom AI endpoints.
- **Lago**: Subscription management.

---

## Features

### Compatibility Flow
- Provides personalized compatibility insights based on user input.
- Handles invalid inputs gracefully and guides users through the process.

### Feedback Handling
- Collects user feedback through interactive buttons and follow-up questions.
- Stores feedback in a structured format for analysis and improvement.

### Language Detection
- Automatically detects the user's language using NLP techniques.
- Supports dynamic language switching for a personalized experience.

### Image Handling
- Detects and politely informs users when unsupported content, such as images, is uploaded in text-based flows.

---

## Deployment & Scalability

### Infrastructure
- **Docker**: Containerized microservices for easy deployment.
- **Kubernetes**: Orchestrates containers for high availability and scalability.

### Scalability
- Horizontally scalable architecture to handle spikes in user traffic.
- Optimized for low-latency responses under heavy load.

---

## Development & Testing

### Local Development
- **Pre-requisites**:
  - Python 3.12+
  - Docker
- **Setup**:
  1. Clone the repository.
  2. Install dependencies using `pip install -r requirements.txt`.
  3. Start services using Docker Compose.

### Testing
- Unit tests for core business logic.
- Integration tests for API endpoints and database interactions.
- Load testing to ensure performance under concurrent user scenarios.

---

## Future Enhancements
- **AI Model Upgrades**: Transition to larger, more accurate LLMs for enhanced user interactions.
- **Multi-Language Support**: Expand support for additional languages.
- **Advanced Analytics**: Provide detailed insights into user behavior and preferences.

---
## API Endpoints

### WhatsApp Endpoints
- **GET /whatsapp**: Webhook verification.
- **POST /whatsapp**: Handle incoming messages.

### Astrology Endpoints
- **POST /generate**: Generate horoscope.
- **POST /compatibility**: Compatibility analysis.
- **POST /chat**: General astrological chat.

### Profile Management
- **POST /profiles/list**: List user profiles.
- **Profile creation**: Via WhatsApp flow.

### Payment Endpoints
- **POST /checkout/start-upi**: Initiate UPI payment.
- **POST /webhook/payment**: Payment confirmation webhook.

---

##  Usage Tracking

### Free Tier
- **3 messages total**.
- **Counter reset**: On new session.

### Paid Plans
- **₹9 Plan**: 2 additional questions.
- **₹49 Plan**: 10 questions.
- **Monthly subscription**: Automatic rollover.

---

## Special Features

### Multi-Language Support
- **English (en)**.
- **Hindi (hi)**.
- **Hinglish (hi-en)**: Romanized Hindi.

### Dynamic Button Generation
- **Context-aware suggestions**.
- **NLP-based intent classification**.
- **Fallback options**: For error states.

### PDF Chart Generation
- **Natal chart visualization**.
- **Automatic sending**: Via WhatsApp.
- **Font availability checking**.

---

##  Error Handling
- **Global exception handler**.
- **Duplicate message prevention**: 5-minute TTL.
- **Graceful degradation**: With fallback responses.
- **Comprehensive logging**: At all levels.

---

##  Performance Optimizations
- **Message deduplication**: With TTL.
- **Connection pooling**: For database queries.
- **Caching**: For city/timezone lookups.
- **Async operations**: Where possible.
- **Batch processing**: For long responses.