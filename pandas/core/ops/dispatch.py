"""
Functions for defining unary operations.
"""
from typing import Any, Callable, Union

import numpy as np

from pandas.errors import NullFrequencyError

from pandas.core.dtypes.common import (
    is_datetime64_dtype,
    is_extension_array_dtype,
    is_integer_dtype,
    is_object_dtype,
    is_scalar,
    is_timedelta64_dtype,
)
from pandas.core.dtypes.generic import ABCExtensionArray, ABCSeries

from pandas._typing import ArrayLike
from pandas.core.construction import array


def should_extension_dispatch(left: ABCSeries, right: Any) -> bool:
    """
    Identify cases where Series operation should use dispatch_to_extension_op.

    Parameters
    ----------
    left : Series
    right : object

    Returns
    -------
    bool
    """
    if (
        is_extension_array_dtype(left.dtype)
        or is_datetime64_dtype(left.dtype)
        or is_timedelta64_dtype(left.dtype)
    ):
        return True

    if not is_scalar(right) and is_extension_array_dtype(right):
        # GH#22378 disallow scalar to exclude e.g. "category", "Int64"
        return True

    return False


def should_series_dispatch(left, right, op):
    """
    Identify cases where a DataFrame operation should dispatch to its
    Series counterpart.

    Parameters
    ----------
    left : DataFrame
    right : DataFrame
    op : binary operator

    Returns
    -------
    override : bool
    """
    if left._is_mixed_type or right._is_mixed_type:
        return True

    if not len(left.columns) or not len(right.columns):
        # ensure obj.dtypes[0] exists for each obj
        return False

    ldtype = left.dtypes.iloc[0]
    rdtype = right.dtypes.iloc[0]

    if (is_timedelta64_dtype(ldtype) and is_integer_dtype(rdtype)) or (
        is_timedelta64_dtype(rdtype) and is_integer_dtype(ldtype)
    ):
        # numpy integer dtypes as timedelta64 dtypes in this scenario
        return True

    if is_datetime64_dtype(ldtype) and is_object_dtype(rdtype):
        # in particular case where right is an array of DateOffsets
        return True

    return False


def dispatch_to_extension_op(
    op,
    left: Union[ABCExtensionArray, np.ndarray],
    right: Any,
    keep_null_freq: bool = False,
):
    """
    Assume that left or right is a Series backed by an ExtensionArray,
    apply the operator defined by op.

    Parameters
    ----------
    op : binary operator
    left : ExtensionArray or np.ndarray
    right : object
    keep_null_freq : bool, default False
        Whether to re-raise a NullFrequencyError unchanged, as opposed to
        catching and raising TypeError.

    Returns
    -------
    ExtensionArray or np.ndarray
        2-tuple of these if op is divmod or rdivmod
    """
    # NB: left and right should already be unboxed, so neither should be
    #  a Series or Index.

    if left.dtype.kind in "mM" and isinstance(left, np.ndarray):
        # We need to cast datetime64 and timedelta64 ndarrays to
        #  DatetimeArray/TimedeltaArray.  But we avoid wrapping others in
        #  PandasArray as that behaves poorly with e.g. IntegerArray.
        left = array(left)

    # The op calls will raise TypeError if the op is not defined
    # on the ExtensionArray

    try:
        res_values = op(left, right)
    except NullFrequencyError:
        # DatetimeIndex and TimedeltaIndex with freq == None raise ValueError
        # on add/sub of integers (or int-like).  We re-raise as a TypeError.
        if keep_null_freq:
            # TODO: remove keep_null_freq after Timestamp+int deprecation
            #  GH#22535 is enforced
            raise
        raise TypeError(
            "incompatible type for a datetime/timedelta "
            "operation [{name}]".format(name=op.__name__)
        )
    return res_values


def maybe_dispatch_ufunc_to_dunder_op(
    self: ArrayLike, ufunc: Callable, method: str, *inputs: ArrayLike, **kwargs: Any
):
    """
    Dispatch a ufunc to the equivalent dunder method.

    Parameters
    ----------
    self : ArrayLike
        The array whose dunder method we dispatch to
    ufunc : Callable
        A NumPy ufunc
    method : {'reduce', 'accumulate', 'reduceat', 'outer', 'at', '__call__'}
    inputs : ArrayLike
        The input arrays.
    kwargs : Any
        The additional keyword arguments, e.g. ``out``.

    Returns
    -------
    result : Any
        The result of applying the ufunc
    """
    # special has the ufuncs we dispatch to the dunder op on
    special = {
        "add",
        "sub",
        "mul",
        "pow",
        "mod",
        "floordiv",
        "truediv",
        "divmod",
        "eq",
        "ne",
        "lt",
        "gt",
        "le",
        "ge",
        "remainder",
        "matmul",
    }
    aliases = {
        "subtract": "sub",
        "multiply": "mul",
        "floor_divide": "floordiv",
        "true_divide": "truediv",
        "power": "pow",
        "remainder": "mod",
        "divide": "div",
        "equal": "eq",
        "not_equal": "ne",
        "less": "lt",
        "less_equal": "le",
        "greater": "gt",
        "greater_equal": "ge",
    }

    # For op(., Array) -> Array.__r{op}__
    flipped = {
        "lt": "__gt__",
        "le": "__ge__",
        "gt": "__lt__",
        "ge": "__le__",
        "eq": "__eq__",
        "ne": "__ne__",
    }

    op_name = ufunc.__name__
    op_name = aliases.get(op_name, op_name)

    def not_implemented(*args, **kwargs):
        return NotImplemented

    if method == "__call__" and op_name in special and kwargs.get("out") is None:
        if isinstance(inputs[0], type(self)):
            name = "__{}__".format(op_name)
            return getattr(self, name, not_implemented)(inputs[1])
        else:
            name = flipped.get(op_name, "__r{}__".format(op_name))
            return getattr(self, name, not_implemented)(inputs[0])
    else:
        return NotImplemented
