"""Core metadata generation and enhancement module for Archipelago"""

import pandas as pd
import json
from typing import Dict, List, Optional
from datetime import datetime
from config import METADATA_SCHEMA, DEFAULT_VALUES, GEO_LOCATION_TEMPLATE
from validator import MetadataValidator


class MetadataGenerator:
    """Generates and enhances metadata for Archipelago ingestion"""
    
    def __init__(self):
        self.validator = MetadataValidator()
        self.metadata_records = []
    
    def create_blank_template(self) -> Dict[str, str]:
        """
        Create a blank metadata template with all fields.
        
        Returns:
            Dict: Empty template with all schema fields
        """
        template = {field: '' for field in METADATA_SCHEMA['all_fields']}
        
        # Add default values for certain fields
        for field, default_value in DEFAULT_VALUES.items():
            if field in template:
                template[field] = default_value
        
        return template
    
    def load_from_csv(self, filepath: str) -> List[Dict[str, str]]:
        """
        Load metadata records from a CSV file.
        
        Args:
            filepath (str): Path to the CSV file
            
        Returns:
            List[Dict]: List of metadata records
        """
        try:
            df = pd.read_csv(filepath, encoding='utf-8')
            self.metadata_records = df.to_dict('records')
            return self.metadata_records
        except Exception as e:
            raise ValueError(f"Error loading CSV file: {str(e)}")
    
    def load_from_json(self, filepath: str) -> List[Dict[str, str]]:
        """
        Load metadata records from a JSON file.
        
        Args:
            filepath (str): Path to the JSON file
            
        Returns:
            List[Dict]: List of metadata records
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                self.metadata_records = json.load(f)
            return self.metadata_records
        except Exception as e:
            raise ValueError(f"Error loading JSON file: {str(e)}")
    
    def enhance_record(self, record: Dict[str, str], options: Optional[Dict] = None) -> Dict[str, str]:
        """
        Enhance a metadata record with additional processing.
        
        Args:
            record (Dict): The metadata record to enhance
            options (Dict): Enhancement options
                - auto_timestamps: Add current timestamp
                - fill_defaults: Fill default values for empty fields
                - normalize_names: Normalize personal/corporate names
                
        Returns:
            Dict: Enhanced metadata record
        """
        if options is None:
            options = {}
        
        enhanced = record.copy()
        
        # Fill in default values if requested
        if options.get('fill_defaults', True):
            for field, default_value in DEFAULT_VALUES.items():
                if field in enhanced and (not enhanced[field] or str(enhanced[field]).strip() == ''):
                    enhanced[field] = default_value
        
        # Add timestamp if requested
        if options.get('auto_timestamps'):
            enhanced['_generation_timestamp'] = datetime.now().isoformat()
        
        # Normalize names if requested
        if options.get('normalize_names'):
            enhanced = self._normalize_names(enhanced)
        
        return enhanced
    
    def _normalize_names(self, record: Dict[str, str]) -> Dict[str, str]:
        """
        Normalize personal and corporate names.
        
        Args:
            record (Dict): The metadata record
            
        Returns:
            Dict: Record with normalized names
        """
        normalized = record.copy()
        
        # Normalize personal names
        for field in METADATA_SCHEMA['personal_name_fields']:
            if field in normalized and normalized[field]:
                # Title case with special handling
                value = str(normalized[field]).strip()
                normalized[field] = self._title_case_name(value)
        
        # Normalize corporate names
        for field in METADATA_SCHEMA['corporate_name_fields']:
            if field in normalized and normalized[field]:
                value = str(normalized[field]).strip()
                normalized[field] = value.title()
        
        return normalized
    
    @staticmethod
    def _title_case_name(name: str) -> str:
        """
        Intelligently title case a name, preserving lowercase articles and prepositions.
        
        Args:
            name (str): The name to format
            
        Returns:
            str: Title-cased name
        """
        articles = {'of', 'and', 'the', 'van', 'von', 'de', 'la', 'le'}
        words = name.split()
        result = []
        
        for i, word in enumerate(words):
            if i == 0:
                result.append(word.title())
            elif word.lower() in articles:
                result.append(word.lower())
            else:
                result.append(word.title())
        
        return ' '.join(result)
    
    def enhance_batch(self, records: Optional[List[Dict[str, str]]] = None,
                      options: Optional[Dict] = None) -> List[Dict[str, str]]:
        """
        Enhance a batch of metadata records.
        
        Args:
            records (List[Dict]): Records to enhance. If None, uses self.metadata_records
            options (Dict): Enhancement options
            
        Returns:
            List[Dict]: Enhanced records
        """
        if records is None:
            records = self.metadata_records
        
        enhanced_records = []
        for record in records:
            enhanced = self.enhance_record(record, options)
            enhanced_records.append(enhanced)
        
        self.metadata_records = enhanced_records
        return enhanced_records
    
    def to_csv(self, filepath: str, records: Optional[List[Dict[str, str]]] = None,
               validate: bool = True) -> Dict:
        """
        Export metadata records to a CSV file.
        
        Args:
            filepath (str): Output file path
            records (List[Dict]): Records to export. If None, uses self.metadata_records
            validate (bool): Whether to validate records before export
            
        Returns:
            Dict: Export summary
        """
        if records is None:
            records = self.metadata_records
        
        if not records:
            raise ValueError("No records to export")
        
        # Validate if requested
        validation_summary = None
        if validate:
            validation_summary = self.validator.validate_batch(records)
            if validation_summary['invalid'] > 0:
                print(f"Warning: {validation_summary['invalid']} invalid records found during export")
        
        # Ensure all fields are present in correct order
        df = pd.DataFrame(records)
        
        # Reorder columns to match schema
        cols_to_include = [col for col in METADATA_SCHEMA['all_fields'] if col in df.columns]
        cols_to_include.extend([col for col in df.columns if col not in METADATA_SCHEMA['all_fields']])
        
        df = df[cols_to_include]
        
        # Fill NaN values with empty strings
        df = df.fillna('')
        
        # Export to CSV
        try:
            df.to_csv(filepath, index=False, encoding='utf-8', quoting=1)  # quoting=1 is QUOTE_ALL
            
            return {
                'success': True,
                'filepath': filepath,
                'records_exported': len(records),
                'fields_exported': len(cols_to_include),
                'validation_summary': validation_summary,
            }
        except Exception as e:
            raise ValueError(f"Error exporting to CSV: {str(e)}")
    
    def to_json(self, filepath: str, records: Optional[List[Dict[str, str]]] = None,
                validate: bool = True) -> Dict:
        """
        Export metadata records to a JSON file.
        
        Args:
            filepath (str): Output file path
            records (List[Dict]): Records to export. If None, uses self.metadata_records
            validate (bool): Whether to validate records before export
            
        Returns:
            Dict: Export summary
        """
        if records is None:
            records = self.metadata_records
        
        if not records:
            raise ValueError("No records to export")
        
        # Validate if requested
        validation_summary = None
        if validate:
            validation_summary = self.validator.validate_batch(records)
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(records, f, indent=2, ensure_ascii=False)
            
            return {
                'success': True,
                'filepath': filepath,
                'records_exported': len(records),
                'validation_summary': validation_summary,
            }
        except Exception as e:
            raise ValueError(f"Error exporting to JSON: {str(e)}")
    
    def get_statistics(self, records: Optional[List[Dict[str, str]]] = None) -> Dict:
        """
        Get statistics about the metadata records.
        
        Args:
            records (List[Dict]): Records to analyze. If None, uses self.metadata_records
            
        Returns:
            Dict: Statistics summary
        """
        if records is None:
            records = self.metadata_records
        
        if not records:
            return {'total_records': 0}
        
        df = pd.DataFrame(records)
        
        stats = {
            'total_records': len(records),
            'total_fields': len(df.columns),
            'fields_populated': {},
            'empty_fields': [],
            'fully_populated_records': 0,
        }
        
        # Calculate field population stats
        for col in df.columns:
            populated = df[col].notna().sum()
            non_empty = (df[col].astype(str).str.strip() != '').sum()
            stats['fields_populated'][col] = {
                'total': len(records),
                'populated': non_empty,
                'percentage': (non_empty / len(records) * 100) if len(records) > 0 else 0,
            }
            
            if non_empty == 0:
                stats['empty_fields'].append(col)
        
        # Count fully populated records
        for _, row in df.iterrows():
            if all(pd.notna(v) and str(v).strip() for v in row):
                stats['fully_populated_records'] += 1
        
        return stats
