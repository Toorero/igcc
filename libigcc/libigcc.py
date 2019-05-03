
# igcc - a read-eval-print loop for C/C++ programmers
#
# Copyright (C) 2009 Andy Balaam
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301, USA.

import itertools
import os
import os.path
import re
import readline
import subprocess
import sys
import tempfile
from colorama import Fore, Style
from optparse import OptionParser

from .source_code import *
from .dot_commands import *
from .version import *

# --------------

# One day these will be in a config file

prompt = Fore.YELLOW + "> " + Style.RESET_ALL

compiler_command = ( "gcc", "-x", "c", "--std=gnu11", "-o", "$outfile", "-",
    "$include_dirs", "$lib_dirs", "$libs" )

compiler_version = ( "g++", "--version" )

include_dir_command = ( "-I$cmd", )
lib_dir_command = ( "-L$cmd", )
lib_command = ( "-l$cmd", )

history_file = '{}/.igcc_history'.format(os.environ['HOME'])
history_size = 1000

#---------------

incl_re = re.compile( r"\s*#\s*include\s" )

#---------------

def read_line_from_stdin( prompt ):
    try:
        return input( prompt )
    except EOFError:
        return None

def read_line_from_file( inputfile, prompt ):
    sys.stdout.write( prompt )
    line = inputfile.readline()
    if line is not None:
        print(line)
    return line

def create_read_line_function( inputfile, prompt ):
    if inputfile is None:
        return lambda: read_line_from_stdin( prompt )
    else:
        return lambda: read_line_from_file( inputfile, prompt )

def get_temporary_file_name():
    outfile = tempfile.NamedTemporaryFile( prefix = 'igcc-exe' )
    outfilename = outfile.name
    outfile.close()
    return outfilename

def append_multiple( single_cmd, cmdlist, ret ):
    if cmdlist is not None:
        for cmd in cmdlist:
            for cmd_part in single_cmd:
                ret.append( cmd_part.replace( "$cmd" , cmd ) )

def get_compiler_command( options, outfilename ):
    ret = []
    for part in compiler_command:
        if part == "$include_dirs":
            append_multiple( include_dir_command, options.INCLUDE, ret )
        elif part == "$lib_dirs":
            append_multiple( lib_dir_command, options.LIBDIR,ret )
        elif part == "$libs":
            append_multiple( lib_command, options.LIB, ret )
        else:
            ret.append( part.replace( "$outfile", outfilename ) )
    return ret


def run_compile( subs_compiler_command, runner ):

    compile_process = subprocess.Popen( subs_compiler_command,
        stdin = subprocess.PIPE, stderr = subprocess.PIPE )

    stdoutdata, stderrdata = compile_process.communicate(
        get_full_source( runner ).encode( 'utf-8') )

    if compile_process.returncode == 0:
        return None
    elif stdoutdata is not None:
        if stderrdata is not None:
            return stdoutdata + stderrdata
        else:
            return stdoutdata
    else:
        if stderrdata is not None:
            return stderrdata
        else:
            return "Unknown compile error - compiler did not write any output."
        

def run_exe( exefilename ):
    run_process = subprocess.Popen( exefilename,
        stdout = subprocess.PIPE, stderr = subprocess.PIPE )
    return run_process.communicate()

def get_compiler_version():
    return subprocess.check_output(
        compiler_version ).decode( 'utf-8' ).strip().split( '\n' )[0]

def print_welcome():
    print( f"""\

{Fore.GREEN}IGCC {VERSION}{Style.RESET_ALL}{Style.BRIGHT}{Fore.BLACK}
Released under GNU GPL version 2 or later, with NO WARRANTY.{Style.RESET_ALL}
Type '.h' for help.
""" )


class UserInput:
    INCLUDE = 0
    COMMAND = 1

    def __init__( self, inp, typ ):
        self.inp = inp
        self.typ = typ
        self.output_chars = 0
        self.error_chars = 0

    def __str__( self ):
        return "UserInput( '{}', {}, {}, {} )".format(
            self.inp,
            self.typ,
            self.output_chars,
            self.error_chars )

    def __eq__( self, other ):
        return (
            self.inp == other.inp and
            self.typ == other.typ and
            self.output_chars == other.output_chars and
            self.error_chars == other.error_chars )

    def __ne__( self, other ):
        return not self.__eq__( other )

class Runner:

    def __init__( self, options, inputfile, exefilename ):
        self.options = options
        self.inputfile = inputfile
        self.exefilename = exefilename
        self.user_input = []
        self.user_functions = []
        self.input_num = 0
        self.compile_error = ""
        self.output_chars_printed = 0
        self.error_chars_printed = 0
        self.paste = False
        self.functions_paste = False

    def do_run( self ):
        read_line = create_read_line_function( self.inputfile, prompt )

        subs_compiler_command = get_compiler_command(
            self.options, self.exefilename )

        inp = 1
        while inp is not None:
            inp = read_line()
            if inp is not None:

                col_inp, run_cmp = (
                    process( inp, self ) )
                if self.functions_paste and inp.strip() != '.f':
                    self.user_functions.append(inp)
                elif col_inp:
                    if self.input_num < len( self.user_input ):
                        self.user_input = self.user_input[ : self.input_num ]
                    if incl_re.match( inp ):
                        typ = UserInput.INCLUDE
                    else:
                        typ = UserInput.COMMAND
                    self.user_input.append( UserInput( inp, typ ) )
                    self.input_num += 1

                if run_cmp and not self.paste and not self.functions_paste:
                    self.compile_error = run_compile(
                        subs_compiler_command, self )

                    if self.compile_error is not None:
                        print( '[Compile error - type .e to see it.]' )
                    else:
                        stdoutdata, stderrdata = run_exe( self.exefilename )
                        stdoutdata = stdoutdata.decode( 'utf-8' )
                        stderrdata = stderrdata.decode( 'utf-8' )

                        if len( stdoutdata ) > self.output_chars_printed:
                            new_output = stdoutdata[self.output_chars_printed:]
                            len_new_output = len( new_output )
                            print( new_output, end='' )
                            self.output_chars_printed += len_new_output
                            self.user_input[ -1 ].output_chars = len_new_output

                        if len( stderrdata ) > self.error_chars_printed:
                            new_error = stderrdata[self.error_chars_printed:]
                            len_new_error = len( new_error )
                            print( new_error, end='' )
                            self.error_chars_printed += len_new_error
                            self.user_input[ -1 ].error_chars = len_new_error

        print()

    def redo( self ):
        if self.input_num < len( self.user_input ):
            self.input_num += 1
            return self.user_input[ self.input_num - 1 ].inp
        else:
            return None


    def undo( self ):
        if self.input_num > 0:
            self.input_num -= 1
            undone_input = self.user_input[ self.input_num ]
            self.output_chars_printed -= undone_input.output_chars
            self.error_chars_printed -= undone_input.error_chars
            return undone_input.inp
        else:
            return None

    def version( self ):
        return get_compiler_version()

    def get_user_input( self ):
        return itertools.islice( self.user_input, 0, self.input_num)

    def get_user_functions( self ):
        return self.user_functions
    
    def get_user_commands( self ):
        return [ a.inp for a in filter(
            lambda a: a.typ == UserInput.COMMAND,
            self.get_user_input() ) ]

    def get_user_includes( self ):
        return [ a.inp for a in filter(
            lambda a: a.typ == UserInput.INCLUDE,
            self.get_user_input() ) ]

    def get_user_functions_string( self ):
        return "\n".join( self.get_user_functions() ) + "\n"

    def get_user_commands_string( self ):
        return "\n".join( self.get_user_commands() ) + "\n"

    def get_user_includes_string( self ):
        return "\n".join( self.get_user_includes() ) + "\n"

def parse_args( argv ):
    parser = OptionParser( version="igcc " + VERSION )
            
    parser.add_option( "-I", "", dest="INCLUDE", action="append",
        help = "Add INCLUDE to the list of directories to " +
            "be searched for header files." )
    parser.add_option( "-L", "", dest="LIBDIR", action="append",
        help = "Add LIBDIR to the list of directories to " +
            "be searched for library files." )
    parser.add_option( "-l", "", dest="LIB", action="append",
        help = "Search the library LIB when linking." )
        
    (options, args) = parser.parse_args( argv )

    if len( args ) > 0:
        parser.error( "Unrecognised arguments :" +
            " ".join( [ arg for arg in args ] ) )

    return options

def run( outputfile = sys.stdout, inputfile = None, print_welc = True,
        argv = None ):

    # TODO: replace try...finally with a "with" statement
    real_sys_stdout = sys.stdout
    sys.stdout = outputfile

    exefilename = ""

    try:
        try:
            options = parse_args( argv )

            exefilename = get_temporary_file_name()
            ret = "normal"
            if print_welc:
                print_welcome()

            if os.path.isfile(history_file):
                readline.read_history_file(history_file)
            else:
                open( history_file, 'a+' ).close()

            Runner( options, inputfile, exefilename ).do_run()

        except IGCCQuitException:
            readline.set_history_length( history_size )
            readline.write_history_file( history_file )

            ret = "quit"
    finally:
        sys.stdout = real_sys_stdout

        if os.path.isfile( exefilename ):
            os.remove( exefilename )

    return ret
