# Owner(s): ["module: onnx"]

"""Test consistency between torch.onnx exported operators and aten operators.

NOTE:

When new ops are supported, please scroll down to modify the EXPECTED_SKIPS_OR_FAILS and
ALLOWLIST_OP lists.

"""
import contextlib
import copy
import dataclasses
import io
import itertools
import unittest
from collections import namedtuple
from typing import (
    Callable,
    Collection,
    Iterable,
    Optional,
    Sequence,
    Tuple,
    Union,
)

import onnx

import torch
from torch.onnx import _constants, verification
from torch.testing._internal import (
    common_device_type,
    common_methods_invocations,
    common_utils,
)
from torch.testing._internal.opinfo import core as opinfo_core

# The min onnx opset version to test for
MIN_ONNX_OPSET_VERSION = 9
# The max onnx opset version to test for
MAX_ONNX_OPSET_VERSION = _constants.ONNX_MAX_OPSET

TESTED_OPSETS = range(MIN_ONNX_OPSET_VERSION, MAX_ONNX_OPSET_VERSION + 1)
ORT_PROVIDERS = ("CPUExecutionProvider",)


SUPPORTED_DTYPES = (
    # Boolean
    torch.bool,
    # Integers
    torch.uint8,
    torch.int8,
    torch.int16,
    torch.int32,
    torch.int64,
    # Floating types
    torch.float16,
    torch.float32,
    torch.float64,
    torch.bfloat16,
    # QInt types
    torch.qint8,
    torch.quint8,
    # Complex types
    torch.complex32,
    torch.complex64,
    torch.complex128,
)

# Convenience tuples for creating dtype lists when skipping or xfailing tests

BOOL_TYPES = (torch.bool,)

INT_TYPES = (
    torch.int8,
    torch.int16,
    torch.int32,
    torch.int64,
    torch.uint8,
)

QINT_TYPES = (
    torch.qint8,
    torch.quint8,
)

FLOAT_TYPES = (
    torch.float16,
    torch.float32,
    torch.float64,
    torch.bfloat16,
)

COMPLEX_TYPES = (
    torch.complex32,
    torch.complex64,
    torch.complex128,
)


# Copied from functorch: functorch/test/common_utils.py
# A named tuple for storing information about a test case to skip
DecorateMeta = namedtuple(
    "DecorateMeta",
    [
        "op_name",
        "variant_name",
        "decorator",
        "device_type",
        "dtypes",
        "reason",
    ],
)


def xfail(
    op_name: str,
    variant_name: str = "",
    *,
    device_type: Optional[str] = None,
    dtypes: Optional[Collection[torch.dtype]] = None,
    reason: str = "unspecified",
):
    """Expects a OpInfo test to fail."""
    return DecorateMeta(
        op_name=op_name,
        variant_name=variant_name,
        decorator=unittest.expectedFailure,
        device_type=device_type,
        dtypes=dtypes,
        reason=reason,
    )


def skip(
    op_name: str,
    variant_name: str = "",
    *,
    device_type: Optional[str] = None,
    dtypes: Optional[Collection[torch.dtype]] = None,
    reason="unspecified",
):
    """Skips a test case in OpInfo."""
    return DecorateMeta(
        op_name=op_name,
        variant_name=variant_name,
        decorator=unittest.skip(reason),
        device_type=device_type,
        dtypes=dtypes,
        reason=reason,
    )


@dataclasses.dataclass
class XfailOpset:
    """Expects a OpInfo test to fail on specific ONNX opsets."""

    op_name: str
    opsets: Collection[Union[int, Callable[[int], bool]]]
    dtypes: Optional[Collection[torch.dtype]] = None
    exception: Optional[Exception] = None
    reason: str = "unspecified"

    def _contains_opset(self, opset: int) -> bool:
        return any(
            opset == opset_spec if isinstance(opset_spec, int) else opset_spec(opset)
            for opset_spec in self.opsets
        )

    def _contains_dtype(self, dtype: torch.dtype) -> bool:
        return self.dtypes is None or dtype in self.dtypes

    def should_fail(self, opset: int, dtype: torch.dtype) -> bool:
        """Returns whether the test should fail for the given opset and dtype."""
        return self._contains_opset(opset) and self._contains_dtype(dtype)


def skip_ops(
    all_opinfos: Sequence[opinfo_core.OpInfo],
    test_case_name: str,
    base_test_name: str,
    to_skip: Iterable[DecorateMeta],
):
    """Decorates OpInfo tests with decorators based on the to_skip list."""
    ops_mapping = {(info.name, info.variant_test_name): info for info in all_opinfos}
    for decorate_meta in to_skip:
        opinfo = ops_mapping.get((decorate_meta.op_name, decorate_meta.variant_name))
        assert opinfo is not None, f"Couldn't find OpInfo for {decorate_meta}"
        decorators = list(opinfo.decorators)
        new_decorator = opinfo_core.DecorateInfo(
            decorate_meta.decorator,
            test_case_name,
            base_test_name,
            device_type=decorate_meta.device_type,
            dtypes=decorate_meta.dtypes,
        )
        decorators.append(new_decorator)
        opinfo.decorators = tuple(decorators)

    # This decorator doesn't modify fn in any way
    def wrapped(fn):
        return fn

    return wrapped


def opsets_before(opset: int) -> Callable[[int], bool]:
    """Returns a comparison function that decides if the given opset is before the specified."""

    def compare(other_opset: int):
        return other_opset < opset

    return compare


def opsets_after(opset: int) -> Callable[[int], bool]:
    """Returns a comparison function that decides if the given opset is after the specified."""

    def compare(other_opset: int):
        return other_opset > opset

    return compare


### Modify this section ###
# NOTE: Modify this section as more ops are supported. The list should be sorted
# alphabetically.

# Ops to be tested for consistency between onnx and pytorch
ALLOWLIST_OP = (
    "ceil",
    "sqrt",
    "t",
)

# Expected failures for onnx export. If an op is expected to fail only for certain
# ONNX opsets, add the op to EXPECTED_OPSET_FAILS below.

EXPECTED_SKIPS_OR_FAILS: Tuple[DecorateMeta, ...] = (
    xfail(
        "ceil",
        dtypes=(torch.bfloat16, torch.float64),
        reason="Ceil not implemented for f64 and bf64 in onnx runtime",
    ),
    skip(
        "ceil",
        dtypes=BOOL_TYPES + INT_TYPES + QINT_TYPES + COMPLEX_TYPES,
        reason="Not supported by onnx",
    ),
    skip(
        "sqrt",
        dtypes=BOOL_TYPES + QINT_TYPES + COMPLEX_TYPES,
        reason="Not supported by onnx",
    ),
    xfail(
        "t",
        dtypes=(torch.bfloat16,) + COMPLEX_TYPES,
        reason="Transpose not implemented for bf64 in onnx runtime",
    ),
)

# Expected opset specific fails for ops that do not support specific opsets

EXPECTED_OPSET_FAILS: Tuple[XfailOpset, ...] = (
    XfailOpset(
        "sqrt",
        dtypes=[torch.bfloat16],
        opsets=[opsets_before(13)],
        reason="sqrt not defined for bf16 before opset 13",
    ),
)

### END OF SECTION TO MODIFY ###


OPS_DB = copy.deepcopy(common_methods_invocations.op_db)


class SingleOpModel(torch.nn.Module):
    """Test model to wrap around a single op for export."""

    def __init__(self, op, kwargs):
        super().__init__()
        self.operator = op
        self.kwargs = kwargs

    def forward(self, *args):
        return self.operator(*args, **self.kwargs)


class TestConsistency(common_utils.TestCase):
    """Test consistency of exported ONNX models.

    This is a parameterized test suite.
    """

    @common_device_type.ops(OPS_DB, allowed_dtypes=SUPPORTED_DTYPES)
    @skip_ops(
        OPS_DB,
        "TestConsistency",
        "test_output_match",
        to_skip=EXPECTED_SKIPS_OR_FAILS,
    )
    def test_output_match(self, device: str, dtype: torch.dtype, op):
        assert device == "cpu"

        if op.name not in ALLOWLIST_OP:
            self.skipTest(f"'{op.name}' is not in the allow list for test on ONNX")

        expected_opset_fails_name_mapping = {
            fail.op_name: fail for fail in EXPECTED_OPSET_FAILS
        }
        samples = op.sample_inputs(
            device,
            dtype,
            requires_grad=False,
        )

        for (cpu_sample, opset) in itertools.product(samples, TESTED_OPSETS):
            model = SingleOpModel(op, cpu_sample.kwargs)

            with self.subTest(sample=cpu_sample, opset=opset):

                # Skip opset specific fails
                if op.name in expected_opset_fails_name_mapping:
                    fail = expected_opset_fails_name_mapping[op.name]
                    if fail.should_fail(opset, dtype):
                        context_manager = self.assertRaises(fail.exception or Exception)
                    else:
                        context_manager = contextlib.nullcontext()
                else:
                    context_manager = contextlib.nullcontext()

                # Run the test
                inputs = (cpu_sample.input, *cpu_sample.args)
                with context_manager:

                    if dtype == torch.bfloat16:
                        # Only export to ONNX without running with onnxruntime because
                        # the CPU execution path for bfloat16 is not implemented in onnxruntime.
                        model_buffer = io.BytesIO()
                        torch.onnx.export(
                            model, inputs, model_buffer, opset_version=opset
                        )
                        model_buffer.seek(0)
                        onnx_model = onnx.load(model_buffer)
                        onnx.checker.check_model(onnx_model, full_check=True)
                        continue

                    verification.verify(
                        model,
                        inputs,
                        input_kwargs={},
                        opset_version=opset,
                        keep_initializers_as_inputs=True,
                        ort_providers=ORT_PROVIDERS,
                        check_shape=True,
                        check_dtype=True,
                        flatten=True,
                    )


common_device_type.instantiate_device_type_tests(
    TestConsistency, globals(), only_for="cpu"
)


if __name__ == "__main__":
    common_utils.run_tests()