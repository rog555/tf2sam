#!/usr/bin/env python3
import argh
from argh import aliases
from argh import arg
from cfn_flip import to_json
from cfn_flip import to_yaml
from collections import namedtuple
from copy import deepcopy
import csv
from datetime import datetime
from dateutil import tz
import hcl
import humps
import jmespath
import json
import jsonschema
from jsonschema.exceptions import ErrorTree
import os
import mergedeep
import re
import sys
from traceback import print_exc


ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
global config
_config = None
REF_PATTERN = re.compile('[$]{[^}]+}')


color = namedtuple('color', 'red green yellow blue bold endc none')(*[
    lambda s, u=c: '\033[%sm%s\033[0m' % (u, s)
    if (sys.platform != 'win32' and u != '') else s
    for c in '91,92,93,94,1,0,'.split(',')
])


def add_utc_tz(x):
    return x.replace(tzinfo=tz.gettz("UTC"))


# custom jmespath functions
class CustomFunctions(jmespath.functions.Functions):
    # regex substitution
    @jmespath.functions.signature(
        {'types': ['string']}, {'types': ['string']}, {'types': ['string']}
    )
    def _func_re_sub(self, pattern, repl, string):
        """regular expression substitution

        """
        if isinstance(string, str):
            return re.sub(pattern, repl, string)
        else:
            return string

    @jmespath.functions.signature(
        {'types': ['object']}, {'types': ['string']}
    )
    def _func_object2keyvalues(self, obj, key_name):
        """convert object to key value list

        """
        return [
            {
                key_name: k,
                'Value': v
            }
            for k, v in obj.items()
        ]

    @jmespath.functions.signature({'types': ['string']}, {'types': ['string']})
    def _func_concat(self, s1, s2):
        """concat one string with another

        """
        return s1 + s2

    @jmespath.functions.signature({'types': ['string']})
    def _pascalize(self, s1):
        """pascalize string

        """
        return humps.pascalize(s1)

    @jmespath.functions.signature({'types': ['string']})
    def _func_ref(self, type_name):
        """convert terraform reference

        """
        return {
            'Ref': transform_type_name(type_name)[1]
        }

    # generate timestamp
    @jmespath.functions.signature()
    def _func_timestamp_number(self):
        """gets timestamp number

        """
        return add_utc_tz(datetime.utcnow()).strftime(
            '%Y%m%d%H%M%S%f'
        )

    @jmespath.functions.signature({'types': ['string']})
    def _func_json_to_obj(self, s1):
        """load json to object

        """
        try:
            return json.loads(s1)
        except Exception:
            error('invalid json in to json_to_obj(): %s' % s1)
            print_exc()
            raise

    @jmespath.functions.signature({'types': ['string']}, {'types': ['array']})
    def _func_expand_array(self, attrs, input_list):
        """generate array from array attributes in array of dicts (!?)

        used for expanding security group ingress/egress cidr_blocks

        """
        output_list = []
        for d in input_list:
            _attrs = {a: d.pop(a, []) for a in attrs.split(',')}
            for attr, vals in _attrs.items():
                _d = d.copy()
                for val in vals:
                    _d[attr] = val
                    output_list.append(_d)
        return output_list


JMESPATH_OPTIONS = jmespath.Options(
    custom_functions=CustomFunctions()
)


def fatal_if_errors(errors, msg=None):
    if not isinstance(errors, list) or len(errors) == 0:
        return
    c = 0
    for e in errors:
        c += 1
        print(color.red('[%s] %s' % (c, e)))
    fatal('%s error(s)%s' % (c, '' if msg is None else ' ' + msg))


def error(msg):
    print(color.red('ERROR: %s' % msg))


def fatal(msg):
    print(color.red('FATAL: %s' % msg))
    sys.exit(1)


def debug(msg):
    print(color.blue('DEBUG:') + msg)


def validate_schema(data, schema_file, msg=None):
    schema = load_file(os.path.join(
        ROOT_DIR, 'config', 'schemas', schema_file
    ))
    jsvalidator = None
    if hasattr(jsonschema, 'Draft7Validator'):
        jsvalidator = jsonschema.Draft7Validator
    else:
        jsvalidator = jsonschema.Draft4Validator

    def _deque_as_string(items):
        return '.'.join([str(item) for item in items])

    def _descriptions(tree):
        results = []
        for error_type, error in tree.errors.items():
            results.append('%s at "%s" as "%s": %s' % (
                error_type,
                _deque_as_string(error.absolute_path),
                _deque_as_string(error.absolute_schema_path),
                error.message
            ))
        for key in tree:
            node = tree[key]
            if isinstance(node, ErrorTree):
                results += _descriptions(node)
        return results
    try:
        fatal_if_errors(
            _descriptions(ErrorTree(jsvalidator(schema).iter_errors(data))),
            msg
        )
    except Exception as e:
        print_exc()
        fatal('unable to load schema %s: %s' % (schema_file, e))


def load_file(file, schema_file=None, csv_keyval=None):
    if not os.path.isfile(file):
        fatal('file %s not found' % file)
    ext = os.path.basename(file).split('.')[-1]
    data = None
    try:
        if ext in ['tf']:
            data = hcl.load(open(file, 'r'))
        elif ext in ['json']:
            data = json.load(open(file, 'r'))
        elif ext in ['yaml']:
            data = json.loads(to_json(open(file, 'r').read()))
        elif ext in ['csv']:
            data = []
            for row in csv.DictReader(open(file, 'r')):
                data.append(row)
        else:
            fatal('%s file format not supported' % ext)
    except Exception as e:
        fatal('unable to load %s: %s' % (file, e))
    if schema_file is not None:
        validate_schema(
            data,
            schema_file,
            'unable to load file %s' % file
        )
    if ext == 'csv' and csv_keyval is not None:
        (key, val) = (
            csv_keyval.split('=', 1)
            if '=' in csv_keyval else (csv_keyval, None)
        )
        data = {
            row[key]: row if val is None else row[val] for row in data
        }
    return data


def config(name):
    global _config
    if _config is not None:
        return _config.get(name, {})
    config_dir = os.path.join(ROOT_DIR, 'config')
    files = [
        f for f in os.listdir(config_dir)
        if os.path.isfile(os.path.join(config_dir, f))
        and os.path.basename(f).split('.')[-1] in ['csv', 'yaml']
    ]
    _config = {}
    csv_keyvals = {
        'resource_type_names.csv': 'terraform=sam',
        'service_names.csv': 'terraform=sam'
    }
    schemas = {
        'aws_.*': 'common.yaml'
    }
    for file in files:
        (_name, ext) = os.path.basename(file).split('.')
        schema_file = file.replace('.' + ext, '.yaml')
        for pattern, _schema_file in schemas.items():
            if re.match(pattern, file):
                schema_file = _schema_file
                break
        _config[_name] = load_file(
            os.path.join(config_dir, file),
            schema_file=schema_file,
            csv_keyval=csv_keyvals.get(file)
        )
    return _config.get(name, {})


def transform_type_name(type_name):
    type_name = strip_ref_attrs(type_name)
    if not type_name.startswith('aws_'):
        return type_name
    (_type, name) = type_name.split('.', 1)
    type_names = config('resource_type_names')
    target_type = type_names.get(_type)
    target_parts = None
    if target_type is not None:
        target_parts = target_type.split('::')
    else:
        target_parts = [humps.pascalize(p) for p in _type.split('_', 2)]
        target_parts[0] = 'AWS'
        target_parts[1] = config('service_names').get(
            target_parts[1].lower(), target_parts[1]
        )
        target_type = '::'.join(target_parts)
    target_name = humps.pascalize(name) + ''.join(target_parts[1:])
    return (target_type, target_name)


def strip_ref_attrs(ref):
    if ref.startswith('${') and ref.endswith('}'):
        ref = ref[2:-1]
    parts = ref.split('.')
    if len(parts) == 3:
        ref = '.'.join(parts[0:2])
    return ref


def find_refs(obj):
    refs = []
    if isinstance(obj, dict):
        for v in obj.values():
            refs += find_refs(v)
    elif isinstance(obj, list):
        for v in obj:
            refs += find_refs(v)
    elif isinstance(obj, str) and '${' in obj and '}' in obj:
        refs = re.findall(REF_PATTERN, obj)
        refs = sorted(list(set([
            strip_ref_attrs(ref)
            for ref in refs
        ])))
    return refs


def expand_variables(obj, refs=None, vars=None):

    if vars is None:
        vars = {}

    def _get_var(ref):
        return ref.split('["')[-1].split('"]')[0]

    def _get_ref_obj(ref, get_attr=False):
        if ref.startswith('${') and ref.endswith('}'):
            ref = ref[2:-1]
        if ref.startswith('var.'):
            _var = _get_var(ref)
            vars[_var] = True
            return {
                'Ref': _var
            }
        elif ref.startswith('AWS::'):
            return '${%s}' % ref
        # TODO() look for hardcoded variables
        # vpc-*
        # subnet-*
        # :accountId:
        # :region:
        parts = ref.split('.')
        type_name = '.'.join(parts[0:2])
        attr = humps.pascalize(parts[-1])
        transformed_type_name = transform_type_name(type_name)[1]
        _obj = None
        if attr in ['Id', 'Arn'] and get_attr is False:
            _obj = {
                'Ref': transformed_type_name
            }
            if isinstance(refs, list):
                refs.append([type_name, transformed_type_name])
        else:
            _obj = {
                'Fn::GetAtt': [transformed_type_name, attr]
            }
        return _obj

    if isinstance(obj, dict):
        for k in obj.keys():
            # don't resolve twice
            if k.startswith('Fn::'):
                continue
            obj[k] = expand_variables(obj[k], refs, vars)
    elif isinstance(obj, list):
        for i in range(len(obj)):
            obj[i] = expand_variables(obj[i], refs, vars)
    elif isinstance(obj, str):
        if obj.startswith('${'):
            obj = _get_ref_obj(obj)
        elif '${' in obj:
            refs = sorted(list(set([
                ref[2:-1] for ref in re.findall(REF_PATTERN, obj)
            ])))
            sub_map = {}
            for ref in refs:
                if ref.startswith('AWS::'):
                    continue
                _ref = ref
                if ref.startswith('var.'):
                    _ref = _get_var(ref)
                    obj = obj.replace(ref, _ref)
                sub_map[_ref] = _get_ref_obj(ref, True)
            obj = {
                'Fn::Sub': [obj, sub_map] if len(sub_map) else obj
            }

    return obj


def jq(query, data):
    try:
        return jmespath.search(query, data, JMESPATH_OPTIONS)
    except Exception as e:
        print_exc()
        fatal('unable to perform jmespath.search(%s, %s): %s' % (
            query, data, e
        ))


def path_update(
    obj, path, val, fn=None, default=False, change_key=False, remove_key=False,
    merge=False
):
    parts = path.split('.')
    parts_len = len(parts)
    updated = False
    for i in range(len(parts)):
        key = parts.pop(0)
        idx = None
        if key[-1] == ']' and '[' in key:
            (key, idx) = key.split('[')
            idx = idx[0:-1]
        if key not in obj:
            if parts_len == i + 1 and default is True:
                obj[key] = fn(val) if callable(fn) else val
                updated = True
            break
        # update last element
        if parts_len == i + 1:
            if idx is None and default is True and merge is False:
                break
            if change_key is True:
                obj[val] = obj[key]
                obj.pop(key, None)
            elif remove_key is True:
                obj.pop(key, None)
            else:
                new_val = fn(val) if callable(fn) else val
                if merge is True:
                    obj[key].update(new_val)
                else:
                    obj[key] = new_val
            updated = True
            break
        obj = obj[key]
        if idx is not None and isinstance(obj, list):
            # update all values in list
            if idx in ['', '*']:
                for j in range(len(obj)):
                    _updated = path_update(
                        obj[j], '.'.join(parts), val, fn, default,
                        change_key, remove_key
                    )
                    if _updated is True:
                        updated = True
            else:
                idx = int(idx)
            # update specific index in list
            if isinstance(idx, int):
                if idx >= parts_len:
                    break
                if parts_len == i + 1:
                    obj[idx] = fn(val) if callable(fn) else val
                    updated = True
                    break
                obj = obj[idx]
    return updated


def get_relationships(resources):
    # build parent/child relationships for merging
    relationships = {}
    for tf_type, tf_resources in resources.items():
        for tf_name, tf_d in tf_resources.items():
            tf_type_name = '%s.%s' % (tf_type, tf_name)
            refs = find_refs(tf_d)
            for ref in refs:

                # parent
                if ref not in relationships:
                    relationships[ref] = {}
                if tf_type not in relationships[ref]:
                    relationships[ref][tf_type] = {}
                relationships[ref][tf_type][tf_name] = True

                # child
                if tf_type_name not in relationships:
                    relationships[tf_type_name] = {}
                (ref_type, ref_name) = ref.split('.')
                if ref_type not in relationships[tf_type_name]:
                    relationships[tf_type_name][ref_type] = {}
                relationships[tf_type_name][ref_type][ref_name] = True

    # convert to dicts to lists
    for _name, _rd in relationships.items():
        for _type in sorted(_rd.keys()):
            relationships[_name][_type] = sorted(_rd[_type].keys())

    return relationships


def _get_api_int_path(ref_obj, all_resources):
    rid = ref_obj.get('resource_id')
    if rid is None:
        return None, []
    paths = []
    c = 0
    merged = []
    while True:
        c += 1
        if c > 50:
            break
        if rid.startswith('${') and rid.endswith('}'):
            rid = rid[2:-1]
        (_type, _name) = strip_ref_attrs(rid).split('.', 1)
        res_obj = all_resources.get(_type, {}).get(_name)
        if not isinstance(res_obj, dict) or 'parent_id' not in res_obj:
            break
        if not _name.endswith('.root_resource_id'):
            merged.append(transform_type_name('%s.%s' % (_type, _name))[1])
        paths.append(res_obj['path_part'])
        rid = res_obj['parent_id']
    return ('/' + '/'.join(reversed(paths)), merged)


def _merge_resources(type_c, pd, relationships, all_resources, refs=None):
    # merge other resources
    merged = []
    _debug = type_c.get('debug')
    for path, md in type_c.get('merge', {}).items():
        if ':' in path:
            path = path.split(':', 1)[0]
        vals = []
        ref_type = md['type']
        if _debug is True:
            debug('merging %s' % path)
        for ref_name in relationships.get(ref_type, []):
            ref_type_name = '%s.%s' % (ref_type, ref_name)
            ref_obj = all_resources.get(ref_type, {}).get(ref_name)
            if ref_obj is not None:
                _merged = []
                if ref_type == 'aws_api_gateway_integration':
                    if 'http_method' in ref_obj:
                        _merged.append(
                            transform_type_name(ref_obj['http_method'])[1]
                        )
                    (ref_obj['_api_path'], _merged2) = _get_api_int_path(
                        ref_obj, all_resources
                    )
                    _merged += _merged2
                # apply filter if specified
                if 'filter' in md:
                    filter_match = jq(md['filter'], ref_obj)
                    if _debug is True:
                        debug('merge filter: %s, match: %s, obj: %s' % (
                            md['filter'], filter_match, ref_obj
                        ))
                    if filter_match is not True:
                        continue

                tx_d = jq(md['transform'], ref_obj)
                if tx_d is not None:
                    # allow transform to specify object key name as ref name
                    if isinstance(tx_d, dict) and '_ref_name_' in tx_d:
                        tx_d[humps.pascalize(ref_name)] = (
                            tx_d.pop('_ref_name_')
                        )
                    vals.append(tx_d)
                    merged += _merged
                    merged.append(transform_type_name(ref_type_name)[1])
        if len(vals) > 0:
            object_type = md.get('object_type', 'array')
            # output type is an object
            if object_type == 'object':
                for val in vals:
                    path_update(
                        pd, path, val, default=True,
                        merge=md.get('merge', False)
                    )
            else:
                # pick the first
                if object_type == 'string':
                    vals = vals[0]
                # array
                path_update(
                    pd, path, vals, default=True, merge=md.get('merge', False)
                )
    for ref_type in type_c.get('merge_exclude_types', []):
        for ref_name in relationships.get(ref_type, []):
            ref_type_name = '%s.%s' % (ref_type, ref_name)
            merged.append(transform_type_name(
                ref_type_name
            )[1])
    if _debug is True:
        debug('merged: %s' % merged)
    return merged


def transform_resource(type, name, d, relationships=None, all_resources=None):
    (target_type, target_name) = transform_type_name(
        type + '.' + name
    )

    type_c = mergedeep.merge(
        {}, config('common'), config(type),
        strategy=mergedeep.Strategy.ADDITIVE
    )
    preserve_case = {}
    errors = []

    if type_c.get('debug') is True and relationships is not None:
        debug('%s.%s relationships: %s' % (
            type, name,
            json.dumps(relationships, indent=2)
        ))

    # preserve case attributes
    for k in type_c.get('preserve_case', []):
        if k not in d:
            continue
        preserve_case[humps.pascalize(k)] = d.pop(k)

    # apply defaults
    for path, val in type_c.get('default', {}).items():
        path_update(d, path, val, default=True)

    # transform attributes
    for path, transform in type_c.get('transform', {}).items():
        path_update(d, path, transform, fn=lambda x: jq(x, d))
        path_update(
            preserve_case, path, transform, fn=lambda x: jq(x, preserve_case)
        )

    # rename attributes
    for path, new_name in type_c.get('rename', {}).items():
        path_update(d, path, new_name, change_key=True)

    pd = humps.pascalize(d)
    pd.update(preserve_case)

    depends_on = pd.pop('DependsOn', None)
    refs = []
    vars = {}
    expand_variables(pd, refs, vars)

    # merge resources
    merged = []
    do_merge = len([k for k in type_c.keys() if k.startswith('merge')]) > 0
    if all([relationships, all_resources]) and do_merge is True:
        merged = _merge_resources(
            type_c, pd, relationships, all_resources, refs
        )

    # remove attributes
    for path in type_c.get('remove', []):
        path_update(pd, path, None, remove_key=True)

    target_d = {
        'Type': target_type,
        'Properties': pd
    }

    # exclude relationships marked as reference to stop
    # cfn-lint complaining about obsolete DependsOn
    if depends_on is not None:
        exclude_depends_on_types = type_c.get('exclude_depends_on_types', [])
        if not isinstance(depends_on, list):
            depends_on = [depends_on]
        _depends_on = []
        target_refs = list(set([_[1] for _ in refs]))
        for ref in depends_on:
            _tf_type = ref.split('.')[0]
            _cf_name = transform_type_name(ref)[1]
            if (_cf_name not in target_refs
               and _tf_type not in exclude_depends_on_types):
                _depends_on.append(_cf_name)
        if len(_depends_on) > 0:
            target_d['DependsOn'] = _depends_on

    _resources_d = {
        target_name: target_d
    }

    # process additions
    for ad in type_c.get('add', []):
        _target_type = ad['type']
        _source_data = deepcopy(d)
        _source_data.update({
            '__type_name__': '%s.%s' % (type, name),
            '__target_type__': target_type,
            '__target_name__': target_name
        })
        if 'filter' in ad:
            if jq(ad['filter'], _source_data) is not True:
                continue
        expand_variables(_source_data, refs, vars)
        _target_name = jq(ad['name_query'], _source_data)
        _target_data = jq(ad['transform'], _source_data)
        if isinstance(_target_name, str) and isinstance(_target_data, dict):
            _resources_d[_target_name] = {
                'Type': _target_type,
                'Properties': _target_data
            }

    return (_resources_d, merged, errors, vars)


@arg('file', help='path to terraform file')
@arg(
    '-p', '--print-yaml',
    help='print generated yaml instead of writing to file'
)
@arg(
    '-f', '--filter',
    help='filter resources on pattern'
)
@aliases('t')
def transform(file, print_yaml=False, filter=None):
    'transform terraform .tf file to sam format'
    if not file.endswith('.tf'):
        fatal('file must end in .tf')
    if not os.path.isfile(file):
        fatal('file not found')
    data = load_file(file)
    if len(data.get('resource', {})) == 0:
        fatal('no resources defined in file %s' % file)
    resources = {}
    target_file = None
    target_txt = None
    merged_names = []
    errors = []

    # resolve any name references
    for rd in config('references').get('name', []):
        tf_type = rd['type']
        tf_attr = rd['name_attribute']
        if tf_type not in data['resource']:
            continue
        for tf_name, tf_d in data['resource'][tf_type].items():
            if tf_attr not in tf_d:
                continue
            data['resource'][tf_type][tf_name][tf_attr] = '${%s.%s.id}' % (
                rd['target_type'], tf_d[tf_attr]
            )

    relationships = get_relationships(data['resource'])
    vars = {}

    for tf_type, tf_resources in data['resource'].items():
        for tf_name, tf_d in tf_resources.items():
            type_name = '%s.%s' % (tf_type, tf_name)
            if filter is not None:
                if re.match('^.*%s.*$' % filter, type_name):
                    print('processing %s' % type_name)
                else:
                    continue
            (_resources_d, _merged, _errors, _vars) = transform_resource(
                tf_type, tf_name, tf_d,
                relationships=relationships.get(type_name),
                all_resources=data['resource']
            )
            vars.update(_vars)
            resources.update(_resources_d)
            errors += _errors
            merged_names += _merged

    for target_name in merged_names:
        resources.pop(target_name, None)
    fatal_if_errors(errors)

    if len(resources) == 0:
        fatal('no resources to write to template')

    target_file = '.'.join(file.split('.')[0:-1]) + '.yaml'
    template = config('template')
    if len(vars) > 0:
        template['Parameters'] = {
            v: {
                'Type': 'String'
            } for v in vars.keys()
        }
    template['Resources'] = resources

    target_txt = to_yaml(json.dumps(template))
    if print_yaml is True:
        print(target_txt)
    else:
        with open(target_file, 'w') as fh:
            fh.write(target_txt)
        print('written %s' % target_file)


def cli():
    parser = argh.ArghParser()
    parser.description = 'Transform Terraform to AWS SAM'
    parser.add_commands([
        transform
    ])
    argh.completion.autocomplete(parser)
    parser.dispatch()


if __name__ == '__main__':
    cli()  # pragma: no cover
