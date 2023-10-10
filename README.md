# Wikidata reverse geocoder

This project offers a reverse geocoding service that returns Wikidata and OpenStreetMap (OSM) information based on geographical coordinates within the UK and Ireland. It uses Python 3 and Flask for the web server, while SQLAlchemy provides database connectivity. This service can look up administrative divisions such as Scottish parishes, English counties, or city districts based on latitude and longitude.

## Overview

The main Python script `lookup.py` performs the following tasks:

- Initializes a Flask application and database
- Provides routes to various API endpoints
- Implements geocoding logic by querying OSM and Wikidata

The `geocode` package consists of:

- `database.py`: Initializes SQLAlchemy session and database engine
- `model.py`: SQLAlchemy model for the database schema
- `scotland.py`: Functions for handling Scottish parishes

## Dependencies

- Python 3.8+
- Flask
- SQLAlchemy
- psycopg2
- GeoAlchemy2
- lxml

## Installation

1. Clone the repository to your local machine.
2. Create a Python virtual environment and install the requirements.
3. Update the configuration settings in `config.default`.
4. Run the Flask application.
5. Set environment variables for database connectivity, if needed.

## Configuration

Create a file named `default.py` in the `config` directory and configure database parameters and other settings. 

Example:

```python
# config.py
DB_URL = "postgresql://username:password@localhost/geocode_db"
```

## Usage

To start the server:

```bash
python lookup.py
```

The web server will start at `http://0.0.0.0:5000`.

## API Endpoints

### Home `/`

Renders the homepage where samples are displayed.

### Random Location `/random`

Displays random UK location details based on latitude and longitude.

### Wikidata Tag `/wikidata_tag`

Returns details based on a specific Wikidata tag.

### Detail Page `/detail`

Displays detail based on latitude and longitude coordinates.

## Database Schema

See `geocode/model.py` for the SQLAlchemy database schema definitions.

## Testing

For now, manual testing is the way to go. Automated tests are planned for future iterations of the project.

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License

This project is licensed under the MIT License.

## Contact

If you have any queries or suggestions, feel free to contact the maintainer, Edward Betts, at edward@4angle.com.
