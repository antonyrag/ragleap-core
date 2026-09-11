package com.ragleap.rag.cost;

/**
 * USD price per 1 million tokens for one provider/model pair.
 * Java equivalent of the {"input": ..., "output": ...} dict values in
 * cost.py's pricing tables.
 */
public record Rate(double input, double output) {
}
