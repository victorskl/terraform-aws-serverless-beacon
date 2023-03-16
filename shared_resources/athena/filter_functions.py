import os
from typing import List, Union

from dynamodb.ontologies import Descendants, Anscestors
from apiutils.requests import OntologyFilter, AlphanumericFilter, CustomFilter, Similarity, Operator
from .analysis import Analysis
from .biosample import Biosample
from .individual import Individual
from .cohort import Cohort
from .dataset import Dataset
from .run import Run
from .common import AthenaModel


ATHENA_TERMS_INDEX_TABLE = os.environ['ATHENA_TERMS_INDEX_TABLE']
ATHENA_RELATIONS_TABLE = os.environ['ATHENA_RELATIONS_TABLE']


queried_athena_models = {a.__name__: a for a in [
    Analysis, Biosample, Individual, Cohort, Dataset, Run]}
id_type_string_to_class = {
    'individuals': Individual,
    'biosamples': Biosample,
    'runs': Run,
    'analyses': Analysis,
    'datasets': Dataset,
    'cohorts': Cohort
}
class_to_id_type_string = {a: b for b, a in id_type_string_to_class.items()}
type_relations_table_id = {
    'individuals': 'individualid',
    'biosamples': 'biosampleid',
    'runs': 'runid',
    'analyses': 'analysisid',
    'datasets': 'datasetid',
    'cohorts': 'cohortid'
}


# given a dict <f>={"operator":X,"value":Y} return appropriate SQL fragment "<operator> <value>"
def _get_comparrison_fragment(f):
    assert "value" in f.keys(), "cannot generate filter query without value specified"
    assert "operator" in f.keys(), "cannot generate filter query without operator specified"

    value = f["value"]
    operator = f["operator"]

    if isinstance(value, int) or isinstance(value, float):  # infer a numeric comparrison
        operator = "!=" if operator == "!" else operator  # '!' operator is odd
        assert operator in [
            "=", "<", ">", "<=", ">=", "!="
        ], "operator for numeric filter must be suported"
    else:  # infer an alphanumeric comparrison
        assert operator in [
            "=", "!"], "operator for string fileter must be supported"
        operator = "LIKE" if operator == "=" else "NOT LIKE"
    return operator, value


def _get_term_ancestors(term):
    terms = set()
    try:
        terms.update(Anscestors.get(term).anscestors)
    except Anscestors.DoesNotExist:
        terms.add(term)
    return terms


def _get_term_descendants(term):
    terms = set()
    try:
        terms.update(Descendants.get(term).descendants)
    except Descendants.DoesNotExist:
        terms.add(term)
    return terms


def entity_search_conditions(filters: List[Union[OntologyFilter, AlphanumericFilter, CustomFilter]], id_type: str, default_scope, id_modifier='id', with_where=True):
    # assert id_type in id_type_string_to_class.keys(), "id_type must be recognised"
    id_class = id_type_string_to_class[id_type]

    # arrays to gradually form the SQL expression
    join_constraints = []
    outer_constraints = []
    # using execution parameters to separately pass to boto3 for it to do SQL sanitization
    join_execution_parameters = []
    outer_execution_parameters = []

    for f in filters:
        # separate and handle filter ids, depending if they are Ontology terms,
        # terms relating directly to the respective table columns
        # or terms relating to tables linked to the respective table

        # assert "id" in f.keys(), "filter without 'id' specified"
        f_id = f.id.split(".")

        # check to see if there is any relevent field of the referred id_type
        if len(f_id) == 1 and f_id[0] in id_class._table_columns:
            operator = '!=' if f.operator == Operator.NOT else f.operator
            outer_constraints.append("{} {} ?".format(f_id[0], operator))
            outer_execution_parameters.append(str(f.value))

        elif len(f_id) == 2 and f_id[0] in queried_athena_models.keys() and f_id[1] in queried_athena_models[f_id[0]]._table_columns:
            joined_class = queried_athena_models[f_id[0]]
            operator = '!=' if f.operator == Operator.NOT else f.operator
            comparrison = "{} {} ?".format(f_id[1], operator)
            join_execution_parameters.append(str(f.value))
            group = class_to_id_type_string[joined_class]
            join_constraints.append(
                f''' SELECT RI.{type_relations_table_id[id_type]} FROM "{ATHENA_RELATIONS_TABLE}" RI JOIN "{joined_class._table_name}" TI ON RI.{type_relations_table_id[group]} = TI.id where TI.{comparrison} ''')

        if isinstance(f, OntologyFilter):
            # by default expanded terms is just the term itself
            expanded_terms = {f.id}
            # if descendantTerms is false, then similarity measures dont really make sense...
            if f.include_descendant_terms:
                # process inclusion of term descendants dependant on 'similarity'
                if f.similarity in (Similarity.HIGH or Similarity.EXACT):
                    expanded_terms = _get_term_descendants(f.id)
                else:
                    # NOTE: this simplistic similarity method not nessisarily efficient or nessisarily desirable
                    ancestors = _get_term_ancestors(f.id)
                    ancestor_descendants = sorted(
                        [_get_term_descendants(a) for a in ancestors], key=len)
                    if f.similarity == Similarity.MEDIUM:
                        # all terms which have an ancestor half way up
                        expanded_terms = ancestor_descendants[len(
                            ancestor_descendants)//2]
                    elif f.similarity == Similarity.LOW:
                        # all terms which have any ancestor in common
                        expanded_terms = ancestor_descendants[-1]

            join_execution_parameters += [str(a) for a in expanded_terms]
            expanded_terms = " , ".join(["?" for a in expanded_terms])
            # process scope clarification if specified different
            group = f.scope or default_scope
            join_constraints.append(
                f''' SELECT RI.{type_relations_table_id[id_type]} FROM "{ATHENA_RELATIONS_TABLE}" RI JOIN "{ATHENA_TERMS_INDEX_TABLE}" TI ON RI.{type_relations_table_id[group]} = TI.id where TI.term IN ({expanded_terms}) ''')

    # format fragments together to form coherent SQL expression
    join_constraints = " INTERSECT ".join(join_constraints)
    join_constraints = f'{id_modifier} IN ({join_constraints}) ' if join_constraints else ''
    total_constraints = (
        [join_constraints] if join_constraints else []) + outer_constraints
    total_constraints = " AND ".join(total_constraints)
    execution_parameters = join_execution_parameters+outer_execution_parameters

    if total_constraints:
        return ("WHERE " if with_where else "") + total_constraints, execution_parameters if execution_parameters else None
    else:
        return "", None
