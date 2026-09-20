{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- set raw_schema = env_var('BQ_RAW_DATASET', 'power_market_raw') -%}
    {%- set output_schema = target.schema if custom_schema_name is none
        else target.schema ~ '_' ~ (custom_schema_name | trim) -%}
    {%- if target.schema in [raw_schema, 'power_market_raw']
        or output_schema in [raw_schema, 'power_market_raw'] -%}
        {{ exceptions.raise_compiler_error('Analytics target must differ from the protected raw dataset') }}
    {%- endif -%}
    {{ output_schema }}
{%- endmacro %}
