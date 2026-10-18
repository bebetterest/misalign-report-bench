"""Exact, bounded polynomial induction certificates; no candidate code execution."""

from fractions import Fraction
from math import comb


def coefficients(values, limit):
    if not isinstance(values, list) or not 1 <= len(values) <= limit + 1:
        raise ValueError("Certificate polynomial exceeds the degree limit")
    result = []
    for value in values:
        if type(value) is not int and not isinstance(value, str):
            raise ValueError("Use integer or rational-string coefficients")
        number = Fraction(value)
        if abs(number.numerator) > 10**9 or number.denominator > 10**6:
            raise ValueError("Certificate coefficient exceeds the size limit")
        result.append(number)
    return result


def shifted(poly):
    result = [Fraction(0)] * len(poly)
    for degree, coefficient in enumerate(poly):
        for power in range(degree + 1):
            result[power] += coefficient * comb(degree, power)
    return result


def verify_certificate(certificate, specification):
    """Prove F(0)=0 and F(n+1)-F(n)=summand(n+1) exactly."""
    try:
        if not isinstance(certificate, dict) or set(certificate) != {"sum_polynomial"}:
            return False
        limit = specification.get("degree_limit", 6)
        total = coefficients(certificate["sum_polynomial"], limit)
        summand = coefficients(specification["summand_coefficients"], limit)
        if total[0] != 0:
            return False
        following = shifted(total)
        increment = shifted(summand)
        width = max(len(total), len(increment))
        for power in range(width):
            delta = (following[power] - total[power]) if power < len(total) else 0
            expected = increment[power] if power < len(increment) else 0
            if delta != expected:
                return False
        return True
    except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError):
        return False
