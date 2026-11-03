"""Monitoring · 持久层.

本模块无独占表 (只读), 目录保留占位以对齐 Wave 2 标准布局.
Monitoring 要查的所有表 (cluster / workspace / training_job / dev_instance) 都走
对应 owner 模块的 CRUD API (例外: monitoring 允许只读).
"""
