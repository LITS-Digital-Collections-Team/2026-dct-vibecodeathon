"""Metadata validation module for Archipelago"""

from typing import Dict, List, Tuple
from config import METADATA_SCHEMA, VALID_TYPES, VALID_LANGUAGES


class MetadataValidator:
    """Validates metadata records against the Archipelago schema"""
    
    def __init__(self):
        self.errors = []
        self.warnings = []
    
    def validate_record(self, record: Dict[str, str]) -> Tuple[bool, List[str], List[str]]:
        """
        Validate a single metadata record.
        
        Args:
            record (Dict): The metadata record to validate
            
        Returns:
            Tuple[bool, List[str], List[str]]: (is_valid, errors, warnings)
        """
        self.errors = []
        self.warnings = []
        
        # Check required fields
        for field in METADATA_SCHEMA['required_fields']:
            if field not in record or not record[field] or str(record[field]).strip() == '':
                self.errors.append(f"Required field '{field}' is missing or empty")
        
        # Validate field values
        self._validate_field_values(record)
        
        # Validate relationships
        self._validate_relationships(record)
        
        return len(self.errors) == 0, self.errors, self.warnings
    
    def _validate_field_values(self, record: Dict[str, str]):
        """Validate individual field values"""
        
        # Validate type field
        if 'type' in record and record['type']:
            if record['type'] not in VALID_TYPES:
                self.warnings.append(
                    f"Type '{record['type']}' not in standard list: {VALID_TYPES}"
                )
        
        # Validate language field
        if 'language' in record and record['language']:
            lang = record['language'].lower()[:2]
            if lang not in VALID_LANGUAGES:
                self.warnings.append(
                    f"Language code '{record['language']}' not recognized"
                )
        
        # Check for file resources
        file_fields = ['audios', 'images', 'models', 'videos', 'documents']
        has_files = any(record.get(field) for field in file_fields)
        if not has_files:
            self.warnings.append("No file resources specified (audios, images, models, videos, documents)")
    
    def _validate_relationships(self, record: Dict[str, str]):
        """Validate relationships between fields"""
        
        # Check if ismemberof has a value
        if 'ismemberof' not in record or not record['ismemberof']:
            self.warnings.append("Field 'ismemberof' is recommended to establish collection membership")
        
        # Check if at least one name field is present when type suggests it
        name_fields = [f for f in METADATA_SCHEMA['personal_name_fields'] if record.get(f)]
        if not name_fields and not any(record.get(f) for f in METADATA_SCHEMA['corporate_name_fields']):
            self.warnings.append("Consider adding at least one personal or corporate name field")
        
        # Validate geographic data consistency
        self._validate_geographic(record)
    
    def _validate_geographic(self, record: Dict[str, str]):
        """Validate geographic field consistency"""
        
        has_geo = bool(record.get('subject_geographic'))
        has_coords = bool(record.get('subject_cartographic_coordinates'))
        has_location = bool(record.get('geographic_location'))
        
        if has_coords and not has_geo:
            self.warnings.append(
                "Has cartographic coordinates but no subject_geographic description"
            )
        
        if has_location and not (has_geo or has_coords):
            self.warnings.append(
                "Has geographic_location but no geographic subject or coordinates"
            )
    
    def validate_batch(self, records: List[Dict[str, str]]) -> Dict:
        """
        Validate a batch of records and return summary statistics.
        
        Args:
            records (List[Dict]): List of metadata records to validate
            
        Returns:
            Dict: Validation summary with counts and details
        """
        valid_count = 0
        invalid_count = 0
        all_errors = {}
        all_warnings = {}
        
        for idx, record in enumerate(records):
            is_valid, errors, warnings = self.validate_record(record)
            
            if is_valid:
                valid_count += 1
            else:
                invalid_count += 1
                all_errors[idx] = errors
            
            if warnings:
                all_warnings[idx] = warnings
        
        return {
            'total': len(records),
            'valid': valid_count,
            'invalid': invalid_count,
            'error_details': all_errors,
            'warning_details': all_warnings,
        }
