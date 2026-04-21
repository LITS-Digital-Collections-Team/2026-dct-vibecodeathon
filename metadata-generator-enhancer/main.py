"""
Archipelago Metadata Generator & Enhancer
Command-line interface for catalogers to generate and enhance metadata for Archipelago ingestion.
"""

import click
import json
import os
from pathlib import Path
from generator import MetadataGenerator
from validator import MetadataValidator
from config import METADATA_SCHEMA


@click.group()
def cli():
    """Archipelago Metadata Generator & Enhancer - A tool for metadata catalogers"""
    pass


@cli.command()
@click.option('--output', '-o', type=click.Path(), default='./output', 
              help='Output directory for generated files')
@click.option('--count', '-c', type=int, default=1,
              help='Number of blank templates to generate')
def template(output, count):
    """Generate blank metadata templates"""
    generator = MetadataGenerator()
    
    os.makedirs(output, exist_ok=True)
    
    for i in range(count):
        template = generator.create_blank_template()
        
        if count == 1:
            filename = os.path.join(output, 'metadata_template.json')
        else:
            filename = os.path.join(output, f'metadata_template_{i+1}.json')
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump([template], f, indent=2, ensure_ascii=False)
        
        click.echo(f'✓ Template created: {filename}')
    
    click.echo(f'\nTotal templates created: {count}')


@cli.command()
@click.argument('input_file', type=click.Path(exists=True))
@click.option('--output', '-o', type=click.Path(), default='./output',
              help='Output directory')
@click.option('--format', '-f', type=click.Choice(['csv', 'json', 'both']), default='csv',
              help='Output format')
@click.option('--enhance', is_flag=True,
              help='Apply enhancement to records')
@click.option('--normalize-names', is_flag=True,
              help='Normalize personal and corporate names')
@click.option('--validate', is_flag=True, default=True,
              help='Validate records before export')
def process(input_file, output, format, enhance, normalize_names, validate):
    """Process and convert metadata files"""
    
    os.makedirs(output, exist_ok=True)
    generator = MetadataGenerator()
    
    try:
        click.echo(f'Loading file: {input_file}...')
        
        # Determine input format and load
        if input_file.endswith('.csv'):
            records = generator.load_from_csv(input_file)
        elif input_file.endswith('.json'):
            records = generator.load_from_json(input_file)
        else:
            click.echo('Error: File must be .csv or .json', err=True)
            return
        
        click.echo(f'✓ Loaded {len(records)} records')
        
        # Enhance if requested
        if enhance:
            click.echo('Enhancing records...')
            options = {
                'fill_defaults': True,
                'normalize_names': normalize_names,
            }
            generator.enhance_batch(options=options)
            click.echo('✓ Records enhanced')
        
        # Export
        basename = Path(input_file).stem
        
        if format in ['csv', 'both']:
            csv_path = os.path.join(output, f'{basename}_output.csv')
            result = generator.to_csv(csv_path, validate=validate)
            click.echo(f'✓ CSV exported: {csv_path}')
            if result.get('validation_summary'):
                summary = result['validation_summary']
                click.echo(f'  Valid records: {summary["valid"]}/{summary["total"]}')
        
        if format in ['json', 'both']:
            json_path = os.path.join(output, f'{basename}_output.json')
            result = generator.to_json(json_path, validate=validate)
            click.echo(f'✓ JSON exported: {json_path}')
        
        click.echo('\n✓ Processing complete!')
        
    except Exception as e:
        click.echo(f'Error: {str(e)}', err=True)


@cli.command()
@click.argument('input_file', type=click.Path(exists=True))
@click.option('--output', '-o', type=click.Path(), default='./output',
              help='Output directory for report')
def validate(input_file, output):
    """Validate metadata records against schema"""
    
    os.makedirs(output, exist_ok=True)
    generator = MetadataGenerator()
    validator = MetadataValidator()
    
    try:
        click.echo(f'Loading file: {input_file}...')
        
        # Load records
        if input_file.endswith('.csv'):
            records = generator.load_from_csv(input_file)
        elif input_file.endswith('.json'):
            records = generator.load_from_json(input_file)
        else:
            click.echo('Error: File must be .csv or .json', err=True)
            return
        
        click.echo(f'✓ Loaded {len(records)} records\n')
        
        # Validate batch
        click.echo('Validating records...')
        summary = validator.validate_batch(records)
        
        # Display results
        click.echo(f'\nValidation Results:')
        click.echo(f'  Total records: {summary["total"]}')
        click.echo(f'  Valid records: {summary["valid"]}')
        click.echo(f'  Invalid records: {summary["invalid"]}')
        
        if summary['invalid'] > 0:
            click.echo(f'\nErrors:')
            for idx, errors in summary['error_details'].items():
                click.echo(f'  Record {idx}:')
                for error in errors:
                    click.echo(f'    - {error}')
        
        if summary['warning_details']:
            click.echo(f'\nWarnings:')
            warning_count = sum(len(w) for w in summary['warning_details'].values())
            click.echo(f'  Total warnings: {warning_count}')
            if warning_count <= 10:
                for idx, warnings in list(summary['warning_details'].items())[:10]:
                    click.echo(f'  Record {idx}:')
                    for warning in warnings:
                        click.echo(f'    - {warning}')
        
        # Save report
        report_path = os.path.join(output, 'validation_report.json')
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        click.echo(f'\n✓ Validation report saved: {report_path}')
        
    except Exception as e:
        click.echo(f'Error: {str(e)}', err=True)


@cli.command()
@click.argument('input_file', type=click.Path(exists=True))
def stats(input_file):
    """Display statistics about metadata records"""
    
    generator = MetadataGenerator()
    
    try:
        click.echo(f'Loading file: {input_file}...')
        
        # Load records
        if input_file.endswith('.csv'):
            records = generator.load_from_csv(input_file)
        elif input_file.endswith('.json'):
            records = generator.load_from_json(input_file)
        else:
            click.echo('Error: File must be .csv or .json', err=True)
            return
        
        click.echo(f'✓ Loaded {len(records)} records\n')
        
        # Get statistics
        statistics = generator.get_statistics(records)
        
        click.echo('Statistics:')
        click.echo(f'  Total records: {statistics["total_records"]}')
        click.echo(f'  Total fields: {statistics["total_fields"]}')
        click.echo(f'  Fully populated records: {statistics["fully_populated_records"]}')
        
        # Show top 10 most populated fields
        click.echo('\nTop 10 Most Populated Fields:')
        fields = sorted(
            statistics['fields_populated'].items(),
            key=lambda x: x[1]['percentage'],
            reverse=True
        )[:10]
        for field, info in fields:
            click.echo(f'  {field}: {info["populated"]}/{info["total"]} ({info["percentage"]:.1f}%)')
        
        # Show empty fields
        if statistics['empty_fields']:
            click.echo(f'\nEmpty Fields ({len(statistics["empty_fields"])}):')
            for field in statistics['empty_fields'][:10]:
                click.echo(f'  - {field}')
            if len(statistics['empty_fields']) > 10:
                click.echo(f'  ... and {len(statistics["empty_fields"]) - 10} more')
        
    except Exception as e:
        click.echo(f'Error: {str(e)}', err=True)


@cli.command()
def schema():
    """Display the metadata schema"""
    
    click.echo('Archipelago Metadata Schema\n')
    click.echo('Required Fields:')
    for field in METADATA_SCHEMA['required_fields']:
        click.echo(f'  - {field}')
    
    click.echo(f'\nAll Available Fields ({len(METADATA_SCHEMA["all_fields"])}):')
    for i, field in enumerate(METADATA_SCHEMA['all_fields'], 1):
        if i % 3 == 0:
            click.echo(f'  {field}')
        else:
            click.echo(f'  {field:<40}', nl=False)
    
    click.echo(f'\n\nField Categories:')
    click.echo(f'  Personal Name Fields: {len(METADATA_SCHEMA["personal_name_fields"])}')
    click.echo(f'  Corporate Name Fields: {len(METADATA_SCHEMA["corporate_name_fields"])}')
    click.echo(f'  Subject Fields: {len(METADATA_SCHEMA["subject_fields"])}')
    click.echo(f'  File Resource Fields: {len(METADATA_SCHEMA["file_resource_fields"])}')


if __name__ == '__main__':
    cli()
