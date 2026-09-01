"""操作编排 mini-VM
==================
功能:
    解释执行 "脚本节点树" (action / operation 两类脚本) 的轻量虚拟机.
    脚本规范形态为结构化节点树 (YAML on disk), VM 直接解释这棵树, 不做文本 DSL / 解析器.
    控制流 (if/for/while/repeat/try/parallel)、类型化作用域变量、HITL、单步调试均在此层实现;
    叶子设备调用复用 action 层 ActionExecutor.

子模块:
    errors  - VM 异常类型 (VmError / VmRaise / VmActionError)
    expr    - 结构化表达式求值 + 变量类型强转 (无 eval)
    schema  - 节点/变量/AID schema 常量 + validate_script + aid_of/resolve_aid
    state   - VM 运行期内存对象 (VmStatus / Variable / Scope / Frame / GlobalEnv)
    thread  - VmThread 递归 async 解释器 (含调试门与 HITL 挂起)
"""
