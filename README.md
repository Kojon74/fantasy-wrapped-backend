# Fantasy Wrapped Backend

This repository contains the backend service for **Fantasy Wrapped**, built using **FastAPI**. The backend is responsible for handling authentication with **Yahoo OAuth** and efficiently calculating various fantasy sports metrics with the **Yahoo Fantasy Sports API**.

## Features

- **FastAPI-powered backend** for handling requests and authentication.
- **OAuth authentication** with Yahoo to securely fetch user fantasy data.
- **Efficient metric calculations** to analyze user performance over the fantasy season.
- **Optimized performance** for handling large-scale data efficiently.

## Performance Optimizations

To ensure fast response times and efficient data processing, the backend implements several performance-enhancing techniques:

1. **Asynchronous Processing**

   - Utilizes FastAPI's built-in support for async/await to handle I/O-bound tasks efficiently.
   - Improves performance by not waiting on blocking operations such as fetching data from the Yahoo Fantasy Sports API.

2. **Staggered Responses & Server-sent Events**

   - Ensures users receive data incrementally, improving time-to-first-byte (TTFB) and reducing the need for long-polling.
   - Uses `asyncio.as_completed` to return results as soon as individual tasks complete, rather than waiting for all tasks to finish.
   - Enables real-time data streaming with Server-Sent Events (SSE), reducing perceived latency and improving responsiveness.

3. **Persistent Caching**

   - Stores calculated metrics in a database after initial computation.
   - Enables faster retrieval when a user revisits the app, avoiding redundant calculations.

4. **Caching**

   - Implements caching mechanisms to store frequently accessed data in memory, reducing redundant API calls.
   - Prevents excessive requests to Yahoo's API, improving speed and reducing the chance of hitting the rate limit.

5. **Batch Requests**

   - Groups multiple API requests into batch calls where possible to minimize network overhead.
   - Uses concurrency for processing multiple league data simultaneously.
