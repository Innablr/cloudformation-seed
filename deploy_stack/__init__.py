from . import deploy_stack


def main():
    d = deploy_stack.StackDeployer()
    d.run()
