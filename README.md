# AAT to Question Bank Migration

This project facilitates the migration of assessment questions from the Alef Assessment Tool (AAT) to a new Question Bank. It includes data mapping for various subjects and sample API requests for fetching question content and assets.

## Project Structure

- `lessonData/`: Contains CSV files for different subjects (Arabic, Biology, Chemistry, English, Islamic, Math, Physics, Science, Social) mapping course codes, LO codes, and question IDs.
- `.env.sample`: A template for environment variables required for API authentication.

## Getting Started

1.  **Environment Setup**:
    Copy `.env.sample` to `.env` and fill in the required values:
    ```bash
    cp .env.sample .env
    ```
    - `BEARER_TOKEN`: Your authorization token.
    - `API_BASE_URL`: Base URL for the assessment service (default: `https://shared.alefed.com/`).
    - `ASSETS_COOKIE`: Required cookie for fetching image assets.

## API Usage Examples

### Fetching a Question by ID

To retrieve a specific question's details using its unique ID:

```bash
curl --location 'https://shared.alefed.com/assessment-question-service/api/questions/{question_id}' \
--header 'Authorization: Bearer YOUR_TOKEN' \
--header 'X-Tenantid: shared'
```

### Searching Questions by Lesson Code

To search for questions associated with specific lesson codes:

```bash
curl --location 'https://shared.alefed.com/assessment-question-service/api/questions/search' \
--header 'Authorization: Bearer YOUR_TOKEN' \
--header 'X-Tenantid: shared' \
--header 'Content-Type: application/json' \
--data '{
    "codes": [{"code": "AR6_MLO_190_Q_51"}]
}'
```

### Fetching Question Images

To download image assets associated with questions:

```bash
curl --location 'https://shared.alefed.com/{path_to_image}.png' \
--header 'accept: image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8' \
--header 'cache-control: no-cache' \
--header 'cookie: YOUR_ASSETS_COOKIE'
```
