import os
from cot.backend.common.fsutils import Search
from cot.loggers import logging
from . import context_tree as ct
from .set_context import set_context
# from .environment import Environment


logger = logging.getLogger('CREATE_TEMPLATE')

# Defaults
CONFIGURATION_REFERENCE_DEFAULT = "unassigned"
REQUEST_REFERENCE_DEFAULT = "unassigned"
DEPLOYMENT_MODE_DEFAULT = "update"
GENERATION_PROVIDERS_DEFAULT = ("aws", )
GENERATION_FRAMEWORK_DEFAULT = "cf"
GENERATION_INPUT_SOURCE_DEFAULT = "composite"


def options(
    environment_obj,
    configuration_reference="",
    deployment_mode="",
    generation_framework="",
    resource_group="",
    generation_input_source="",
    level="",
    output_dir="",
    generation_providers=None,
    request_reference="",
    region="",
    deployment_unit="",
    deployment_unit_subset=""
):
    e = environment_obj
    # updating environment to use vars in other functions where direct env access required
    e.RESOURCE_GROUP = resource_group
    e.LEVEL = level
    e.OUTPUT_DIR = output_dir
    e.REGION = region
    e.DEPLOYMENT_UNIT = deployment_unit
    e.DEPLOYMENT_UNIT_SUBSET = deployment_unit_subset
    # Defaults
    e.CONFIGURATION_REFERENCE = configuration_reference or CONFIGURATION_REFERENCE_DEFAULT
    e.REQUEST_REFERENCE = request_reference or REQUEST_REFERENCE_DEFAULT
    e.DEPLOYMENT_MODE = deployment_mode or DEPLOYMENT_MODE_DEFAULT
    e.GENERATION_FRAMEWORK = generation_framework or GENERATION_FRAMEWORK_DEFAULT
    e.GENERATION_INPUT_SOURCE = generation_input_source or GENERATION_FRAMEWORK_DEFAULT
    e.GENERATION_PROVIDERS = generation_providers or GENERATION_PROVIDERS_DEFAULT

    if not ct.is_valid_unit(e.LEVEL, e.DEPLOYMENT_UNIT):
        logger.fatal('Deployment unit/level not valid')
        return False
    if not e.CONFIGURATION_REFERENCE or not e.REQUEST_REFERENCE:
        logger.fatal('request/configuration reference not provided')
        return False
    # Input control for composite/CMDB input
    if e.GENERATION_INPUT_SOURCE == 'composite':
        # Set up context
        set_context(os.getcwd(), e)
        # Ensure we are in the right place
        if e.LEVEL == 'account':
            if e.LEVEL in e.LOCATION:
                logger.fatal('Current directory doen\'t match request level "%s"', e.LEVEL)
                return False
        elif e.LEVEL in ('solution', 'segment', 'application', 'blueprint', 'unitlist'):
            if 'segment' in e.LOCATION:
                logger.fatal('Current directory doen\'t match request level "%s"', e.LEVEL)
                return False
        # Add default composite fragments including end fragment
        if (
            e.GENERATION_USE_CACHE != 'true'
            and e.GENERATION_USE_FRAGMENTS_CACHE != 'true'
            or os.path.isfile(os.path.join(e.CACHE_DIR, 'composite_account.ftl'))
        ):
            for composite in e.TEMPLATE_COMPOSITES:
                # only support provision of fragment files via cmdb
                # others can now be provided via the plugin mechanism
                composite_array_name = f'{composite}_array'
                composite_array = e.get(composite_array_name, [])
                e[composite_array_name] = composite_array
                if composite == 'fragment':
                    for blueprint_alternate_dir in e.blueprint_alternate_dirs:
                        if not blueprint_alternate_dir or not os.path.isdir(blueprint_alternate_dir):
                            continue
                        for fragment in Search.match_files(f'{composite}_*.ftl', root=blueprint_alternate_dir):
                            fragment_name = os.path.basename(fragment)
                            if fragment_name not in composite_array:
                                composite_array.append(fragment)
                    # Legacy fragments
                    pattern = os.path.join(e.GENERATION_DIR, 'templates', composite, f'{composite}_*.ftl')
                    for fragment in Search.match_files(pattern):
                        fragment_name = os.path.basename(fragment)
                        if fragment_name not in composite_array:
                            composite_array.append(fragment)
                    # Legacy end fragments
                    pattern = os.path.join(e.GENERATION_DIR, 'templates', composite, '*end.ftl')
                    for fragment in Search.match_files(pattern):
                        fragment_name = os.path.basename(fragment)
                        if fragment_name not in composite_array:
                            composite_array.append(fragment)
            # create the template composites
            for composite in e.TEMPLATE_COMPOSITES:
                with open(os.path.join(e.CACHE_DIR, f'composite_{composite}.ftl', 'at+')) as composite_file:
                    for filename in composite_array:
                        filename = os.path.join(filename)
                        if not os.path.isfile(filename):
                            continue
                        with open(filename, 'rt') as f:
                            composite_file.write(f.read())

            for composite in ('segment', 'solution', 'application', 'id', 'name', 'policy', 'resource'):
                filename = os.path.join(e.CACHE_DIR, f'{composite}.ftl')
                if os.path.isfile(filename):
                    os.remove(filename)
        # Assemble settings
        e.COMPOSITE_SETTINGS = os.path.join(e.CACHE_DIR, 'composite_settings.json')
        if (
            e.GENERATION_USE_CACHE != 'true'
            and e.GENERATION_USE_SETTINGS_CACHE != 'true'
            or not os.path.isfile(e.COMPOSITE_SETTINGS)
        ):
            logger.debug('Generating composite settings ...')
            ct.assemble_settings(e)
        # Create the composite definitions
        e.COMPOSITE_DEFINITIONS = os.path.join(e.CACHE_DIR, 'composite_definitions.json')
        if (
            e.GENERATION_USE_CACHE != 'true'
            and e.GENERATION_USE_DEFINITIONS_CACHE != 'true'
            or not os.path.isfile(e.COMPOSITE_DEFINITIONS)
        ):
            ct.assemble_composite_definitions(e)
        # Create the composite stack outputs
        e.COMPOSITE_STACK_OUTPUTS = os.path.join(e.CACHE_DIR, 'composite_stack_outputs.json')
        if (
            e.GENERATION_USE_CACHE != 'true'
            and e.GENERATION_USE_STACK_OUTPUTS_CACHE != 'true'
            or not os.path.isfile(e.COMPOSITE_STACK_OUTPUTS)
        ):
            ct.assemble_composite_stack_outputs(e)
    # Specific intput control for mock input
    if e.GENERATION_INPUT_SOURCE == 'mock':
        if not e.OUTPUT_DIR:
            logger.fatal('Generation input source mock requires output dir to be specified')
            return False


def process_template(
    level="",
    deployment_unit="",
    resource_group="",
    deployment_unit_subset="",
    account="",
    account_region="",
    region="",
    request_reference="",
    configuration_reference="",
    deployment_mode=""
):
    pass


def create_template(
    configuration_reference="",
    deployment_mode="",
    generation_framework="",
    resource_group="",
    generation_input_source="",
    level="",
    output_dir="",
    generation_providers=None,
    request_reference="",
    region="",
    deployment_unit="",
    deployment_unit_subset=""
):
    pass
