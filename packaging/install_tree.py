#!/usr/bin/env python3
"""Stage the application for distro packagers; does not install dependencies."""
import argparse
from common import install_tree

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destdir', required=True)
    parser.add_argument('--prefix', default='/usr')
    args = parser.parse_args()
    print(install_tree(args.destdir, args.prefix))
