# Configuration and Schema Definition for Archipelago Metadata Generator

# Define the complete metadata schema
METADATA_SCHEMA = {
    'required_fields': [
        'local_identifier',
        'title',
        'type',
        'genre',
        'subgenre_audiovisual_materials',
        'subgenre_ephemera',
        'subgenre_manuscripts',
        'subgenre_publications',
        'subgenre_visual_materials',
        'ismemberof',
        'description',
        'rights_statements',
    ],
    'all_fields': [
        'local_identifier',
        'title',
        'subtitle',
        'title_alternative',
        'sort_order',
        'series_title',
        'description',
        'provenance',
        'note',
        'abstract',
        'date_full',
        'date_note',
        'personal_name',
        'personal_name_addressee',
        'personal_name_artist',
        'personal_name_author',
        'personal_name_cartographer',
        'personal_name_compiler',
        'personal_name_composer',
        'personal_name_contributor',
        'personal_name_dedicatee',
        'personal_name_editor',
        'personal_name_illustrator',
        'personal_name_interviewee',
        'personal_name_interviewer',
        'personal_name_owner',
        'personal_name_photographer',
        'personal_name_publisher',
        'personal_name_publishingdirector',
        'personal_name_speaker',
        'personal_name_translator',
        'corporate_name',
        'corporate_name_addressee',
        'corporate_name_author',
        'corporate_name_owner',
        'corporate_name_photographer',
        'family_name',
        'type',
        'genre',
        'subgenre_audiovisual_materials',
        'subgenre_ephemera',
        'subgenre_manuscripts',
        'subgenre_publications',
        'subgenre_visual_materials',
        'publisher_name',
        'place_of_publication',
        'language',
        'extent',
        'table_of_contents',
        'building_name',
        'subject_personal_name',
        'subject_corporate_name',
        'subject_family_name',
        'subject_geographic',
        'subject_cartographic_coordinates',
        'geographic_location',
        'subject_topical',
        'ismemberof',
        'ispartof',
        'sequence_id',
        'shelf_location',
        'physical_location',
        'restrictions_on_access',
        'rights_statements',
        'audios',
        'images',
        'models',
        'videos',
        'documents',
    ],
    'personal_name_fields': [
        'personal_name',
        'personal_name_addressee',
        'personal_name_artist',
        'personal_name_author',
        'personal_name_cartographer',
        'personal_name_compiler',
        'personal_name_composer',
        'personal_name_contributor',
        'personal_name_dedicatee',
        'personal_name_editor',
        'personal_name_illustrator',
        'personal_name_interviewee',
        'personal_name_interviewer',
        'personal_name_owner',
        'personal_name_photographer',
        'personal_name_publisher',
        'personal_name_publishingdirector',
        'personal_name_speaker',
        'personal_name_translator',
    ],
    'corporate_name_fields': [
        'corporate_name',
        'corporate_name_addressee',
        'corporate_name_author',
        'corporate_name_owner',
        'corporate_name_photographer',
    ],
    'subject_fields': [
        'subject_personal_name',
        'subject_corporate_name',
        'subject_family_name',
        'subject_geographic',
        'subject_cartographic_coordinates',
        'subject_topical',
    ],
    'geographic_fields': [
        'subject_geographic',
        'geographic_location',
    ],
    'file_resource_fields': [
        'audios',
        'images',
        'models',
        'videos',
        'documents',
    ]
}

# Default values for constant fields
DEFAULT_VALUES = {
    'restrictions_on_access': 'There are no restrictions on access to this resource.',
    'language': 'en',
    'type': 'object',
}

# Example geographic location structure
GEO_LOCATION_TEMPLATE = {
    "lat": "",
    "lng": "",
    "city": "",
    "state": "",
    "value": "",
    "county": "",
    "osm_id": "",
    "country": "",
    "category": "",
    "locality": "",
    "osm_type": "",
    "postcode": "",
    "country_code": "",
    "display_name": "",
    "neighbourhood": "",
    "state_district": ""
}

# Nominatim API settings for geographic lookup
NOMINATIM_SETTINGS = {
    'enabled': True,
    'user_agent': 'archipelago-metadata-generator/1.0',
    'timeout': 10,
}

# Valid values for certain fields
VALID_TYPES = [
    'object',
    'collection',
    'image',
    'sound',
    'text',
    'video',
    'map',
    'thesis',
    'publication',
]

VALID_LANGUAGES = [
    'en', 'es', 'fr', 'de', 'it', 'pt', 'zh', 'ja', 'ko', 'ru', 'ar', 'hi',
]

# Output configuration
OUTPUT_ENCODING = 'utf-8'
OUTPUT_DELIMITER = ','
OUTPUT_QUOTING = 'minimal'
